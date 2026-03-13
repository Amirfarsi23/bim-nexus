import anthropic
import os
from dotenv import load_dotenv

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

GRAPH_SCHEMA = """
You are a Neo4j Cypher expert for a BIM building database.

The graph has these nodes:
- Building {name}
- Floor {guid, name, level}
- Space {guid, name, long_name, area}
- Wall {guid, name, is_external}
- Door {guid, name, width, height}
- Window {guid, name, width, height}

The graph has these relationships:
- (Building)-[:HAS_FLOOR]->(Floor)
- (Floor)-[:CONTAINS]->(Space)
- (Floor)-[:HAS_WALL]->(Wall)
- (Floor)-[:HAS_DOOR]->(Door)
- (Floor)-[:HAS_WINDOW]->(Window)
- (Wall)-[:BOUNDS]->(Space)
- (Door)-[:OPENS_INTO]->(Space)
- (Window)-[:BELONGS_TO]->(Space)

Return ONLY the Cypher query, nothing else.
No explanation, no markdown, just the query.
"""


def question_to_cypher(question):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=GRAPH_SCHEMA,
        messages=[{"role": "user", "content": question}]
    )
    return response.content[0].text.strip()


def results_to_answer(question, results):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content":
            f"Question: {question}\n"
            f"Data from database: {results}\n"
            f"Answer in one clear professional sentence."
        }]
    )
    return response.content[0].text.strip()


def answer_question(question, driver):
    cypher = question_to_cypher(question)
    print(f"Generated Cypher: {cypher}")

    with driver.session() as session:
        results = session.run(cypher).data()

    answer = results_to_answer(question, results)
    return answer


if __name__ == "__main__":
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"),
              os.getenv("NEO4J_PASSWORD"))
    )
    answer = answer_question("How many rooms are in the building?", driver)
    print(f"\nAnswer: {answer}")
    driver.close()