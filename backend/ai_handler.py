import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

GRAPH_SCHEMA_TEMPLATE = """
You are a Neo4j Cypher expert for a BIM building database.

NODES and their properties:
- Building  {{name, user_id, project_id}}
- Floor     {{guid, name, level, user_id, project_id}}
- Space     {{guid, name, long_name, area, height, volume, user_id, project_id}}
- Wall      {{guid, name, is_external, material, wall_type, user_id, project_id}}
- Door      {{guid, name, width, height, area, user_id, project_id}}
- Window    {{guid, name, width, height, area, user_id, project_id}}
- Furniture {{guid, name, user_id, project_id}}

RELATIONSHIPS:
- (Building)-[:HAS_FLOOR]    ->(Floor)
- (Floor)   -[:CONTAINS]     ->(Space)
- (Floor)   -[:HAS_WALL]     ->(Wall)
- (Floor)   -[:HAS_DOOR]     ->(Door)
- (Floor)   -[:HAS_WINDOW]   ->(Window)
- (Wall)    -[:BOUNDS]       ->(Space)   has properties: {{area, length, height, wall_type}}
- (Door)    -[:OPENS_INTO]   ->(Space)   has properties: {{area}}
- (Window)  -[:BELONGS_TO]   ->(Space)   has properties: {{area}}
- (Space)   -[:HAS_FURNITURE]->(Furniture)

CRITICAL RULE:
Every single node match MUST include user_id and project_id filters.
Use exactly:
  user_id:    '{user_id}'
  project_id: '{project_id}'

ROOM NAMES IN THIS MODEL: {room_names}
WALL TYPES IN THIS MODEL: {wall_types}

EXAMPLE QUERIES:

Q: How many rooms?
A: MATCH (s:Space {{user_id: '{user_id}', project_id: '{project_id}'}}) RETURN COUNT(s) AS total_rooms

Q: Total floor area?
A: MATCH (s:Space {{user_id: '{user_id}', project_id: '{project_id}'}}) RETURN SUM(s.area) AS total_area

Q: Ceramic area in bathroom?
A: MATCH (w:Wall {{user_id: '{user_id}', project_id: '{project_id}'}})-[b:BOUNDS]->(s:Space {{user_id: '{user_id}', project_id: '{project_id}'}}) WHERE w.wall_type='ceramic' AND s.long_name='Bathroom' RETURN SUM(b.area) AS ceramic_area

Q: Total ceramic area?
A: MATCH (w:Wall {{user_id: '{user_id}', project_id: '{project_id}'}})-[b:BOUNDS]->(s:Space {{user_id: '{user_id}', project_id: '{project_id}'}}) WHERE w.wall_type='ceramic' RETURN s.long_name AS room, SUM(b.area) AS ceramic_area

Q: Which walls are external?
A: MATCH (w:Wall {{user_id: '{user_id}', project_id: '{project_id}'}}) WHERE w.is_external=true RETURN w.name, w.wall_type

Q: Furniture in bedroom?
A: MATCH (s:Space {{user_id: '{user_id}', project_id: '{project_id}', long_name:'Bed room'}})-[:HAS_FURNITURE]->(f:Furniture) RETURN f.name

Q: Wall area in bathroom?
A: MATCH (w:Wall {{user_id: '{user_id}', project_id: '{project_id}'}})-[b:BOUNDS]->(s:Space {{user_id: '{user_id}', project_id: '{project_id}', long_name:'Bathroom'}}) RETURN w.wall_type, SUM(b.area) AS area

Q: Total painting area?
A: MATCH (w:Wall {{user_id: '{user_id}', project_id: '{project_id}'}})-[b:BOUNDS]->(s:Space {{user_id: '{user_id}', project_id: '{project_id}'}}) WHERE w.wall_type IN ['structural','drywall','general'] RETURN SUM(b.area) AS painting_area

Return ONLY the Cypher query.
No explanation, no markdown, no backticks, just the query.
"""


def get_model_context(driver, user_id, project_id):
    """Fetch actual room names and wall types from this user's model."""
    with driver.session() as session:
        rooms = session.run("""
            MATCH (s:Space {user_id: $uid, project_id: $pid})
            RETURN DISTINCT s.long_name AS name
        """, uid=user_id, pid=project_id).data()

        walls = session.run("""
            MATCH (w:Wall {user_id: $uid, project_id: $pid})
            RETURN DISTINCT w.wall_type AS type
        """, uid=user_id, pid=project_id).data()

    room_names = [r["name"] for r in rooms if r["name"]]
    wall_types  = [w["type"] for w in walls if w["type"]]
    return room_names, wall_types


def question_to_cypher(question, user_id, project_id, driver):
    """Convert natural language to Cypher scoped to this user's project."""
    room_names, wall_types = get_model_context(driver, user_id, project_id)

    schema = GRAPH_SCHEMA_TEMPLATE.format(
        user_id    = user_id,
        project_id = project_id,
        room_names = room_names,
        wall_types = wall_types
    )

    response = client.messages.create(
        model      = "claude-sonnet-4-6",
        max_tokens = 500,
        system     = schema,
        messages   = [{"role": "user", "content": question}]
    )
    cypher = response.content[0].text.strip()
    cypher = cypher.replace("```cypher", "").replace("```", "").strip()
    return cypher


def results_to_answer(question, results):
    """Convert raw Neo4j results into a readable answer."""
    response = client.messages.create(
        model      = "claude-sonnet-4-6",
        max_tokens = 300,
        messages   = [{"role": "user", "content":
            f"Question: {question}\n"
            f"Database results: {results}\n"
            f"Write a clear professional answer in one or two sentences. "
            f"Include specific numbers and units (m², count etc). "
            f"If results are empty say what was not found."
        }]
    )
    return response.content[0].text.strip()


def answer_question(question, driver, user_id, project_id):
    """Full pipeline: question → Cypher → Neo4j → human answer."""
    cypher = question_to_cypher(question, user_id, project_id, driver)
    print(f"Generated Cypher: {cypher}")

    try:
        with driver.session() as session:
            results = session.run(cypher).data()
        print(f"Results: {results}")
    except Exception as e:
        print(f"Cypher error: {e}")
        return "I could not process that query. Try rephrasing your question."

    if not results:
        return "No data found for that query. Try asking differently."

    return results_to_answer(question, results)


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    )
    tests = [
        "How many rooms are in the building?",
        "What is the total ceramic area?",
        "What furniture is in the bedroom?",
        "What is the total floor area?"
    ]
    for q in tests:
        print(f"\nQ: {q}")
        print(f"A: {answer_question(q, driver, 'test_user', 'test_project')}")
    driver.close()
