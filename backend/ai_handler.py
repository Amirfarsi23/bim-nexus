import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

GRAPH_SCHEMA = """
You are a Neo4j Cypher expert for a BIM building database.

NODES and their properties:
- Building  {name}
- Floor     {guid, name, level}
- Space     {guid, name, long_name, area, height, volume}
- Wall      {guid, name, is_external, material, wall_type}
- Door      {guid, name, width, height, area}
- Window    {guid, name, width, height, area}
- Furniture {guid, name}

RELATIONSHIPS:
- (Building)-[:HAS_FLOOR]    ->(Floor)
- (Floor)   -[:CONTAINS]     ->(Space)
- (Floor)   -[:HAS_WALL]     ->(Wall)
- (Floor)   -[:HAS_DOOR]     ->(Door)
- (Floor)   -[:HAS_WINDOW]   ->(Window)
- (Wall)    -[:BOUNDS]       ->(Space)  has properties: {area, length, height, wall_type}
- (Door)    -[:OPENS_INTO]   ->(Space)  has properties: {area}
- (Window)  -[:BELONGS_TO]   ->(Space)  has properties: {area}
- (Space)   -[:HAS_FURNITURE]->(Furniture)

IMPORTANT DATA VALUES:
- wall_type values: 'ceramic', 'glass', 'drywall', 'structural', 'general'
- is_external values: true or false
- Space long_name values: 'Bed room', 'Livingroom', 'Kitchen', 'Bathroom', 'WC'
- Space name values: '1', '2', '3', '4', '5'
- ceramic walls are finish walls (tiles) in Bathroom and WC
- glass walls are in Bathroom
- Furniture names: Bett (bed), Sofa, Küchenzeile (kitchen units)

EXAMPLE QUERIES:
Q: How many rooms?
A: MATCH (s:Space) RETURN COUNT(s) AS total_rooms

Q: Total floor area?
A: MATCH (s:Space) RETURN SUM(s.area) AS total_area

Q: Ceramic area in bathroom?
A: MATCH (w:Wall)-[b:BOUNDS]->(s:Space) WHERE w.wall_type='ceramic' AND s.long_name='Bathroom' RETURN SUM(b.area) AS ceramic_area

Q: Total ceramic area?
A: MATCH (w:Wall)-[b:BOUNDS]->(s:Space) WHERE w.wall_type='ceramic' RETURN s.long_name AS room, SUM(b.area) AS ceramic_area

Q: Which walls are external?
A: MATCH (w:Wall) WHERE w.is_external=true RETURN w.name, w.wall_type

Q: Furniture in bedroom?
A: MATCH (s:Space {long_name:'Bed room'})-[:HAS_FURNITURE]->(f:Furniture) RETURN f.name

Q: Wall area in bathroom?
A: MATCH (w:Wall)-[b:BOUNDS]->(s:Space {long_name:'Bathroom'}) RETURN w.wall_type, SUM(b.area) AS area

Q: Total painting area?
A: MATCH (w:Wall)-[b:BOUNDS]->(s:Space) WHERE w.wall_type IN ['structural','drywall','general'] RETURN SUM(b.area) AS painting_area

Return ONLY the Cypher query.
No explanation, no markdown, no backticks, just the query.
"""


def question_to_cypher(question):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=GRAPH_SCHEMA,
        messages=[{"role": "user", "content": question}]
    )
    cypher = response.content[0].text.strip()
    # Remove any markdown formatting if present
    cypher = cypher.replace("```cypher", "").replace("```", "").strip()
    return cypher


def results_to_answer(question, results):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content":
            f"Question: {question}\n"
            f"Database results: {results}\n"
            f"Write a clear professional answer in one or two sentences. "
            f"Include specific numbers and units (m², count etc). "
            f"If results are empty say what was not found."
        }]
    )
    return response.content[0].text.strip()


def answer_question(question, driver):
    cypher = question_to_cypher(question)
    print(f"Generated Cypher: {cypher}")

    try:
        with driver.session() as session:
            results = session.run(cypher).data()
        print(f"Results: {results}")
    except Exception as e:
        print(f"Cypher error: {e}")
        return f"I could not process that query. Try rephrasing your question."

    if not results:
        return "No data found for that query. Try asking differently."

    answer = results_to_answer(question, results)
    return answer


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"),
              os.getenv("NEO4J_PASSWORD"))
    )
    # Test questions
    tests = [
        "How many rooms are in the building?",
        "What is the total ceramic area?",
        "What furniture is in the bedroom?",
        "What is the total floor area?"
    ]
    for q in tests:
        print(f"\nQ: {q}")
        answer = answer_question(q, driver)
        print(f"A: {answer}")
    driver.close()
