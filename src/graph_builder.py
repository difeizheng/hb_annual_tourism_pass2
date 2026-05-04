"""Graph builder: construct knowledge graph using NetworkX (with Neo4j export support)."""

import json
import os

import networkx as nx


def build_graph(
    cleaned_spots: list[dict],
    alignment_result: dict,
    data_dir: str | None = None,
) -> nx.MultiDiGraph:
    """Build a knowledge graph from cleaned spot data.

    Node types: spot, pass, city, area, category
    Edge types: INCLUDED_IN, LOCATED_IN, BELONGS_TO_CITY, HAS_CATEGORY, SAME_AS
    """
    G = nx.MultiDiGraph()

    # Add pass nodes
    pass_names = set()
    for spot in cleaned_spots:
        pass_names.add(spot["pass_name"])

    for pn in pass_names:
        G.add_node(f"pass:{pn}", type="pass", name=pn)

    # Add city nodes
    cities = set()
    for spot in cleaned_spots:
        cities.add(spot["city"])

    for city in cities:
        G.add_node(f"city:{city}", type="city", name=city)

    # Add category nodes
    categories = set()
    for spot in cleaned_spots:
        cat = spot.get("_classification", {}).get("category", "其他")
        categories.add(cat)

    for cat in categories:
        G.add_node(f"category:{cat}", type="category", name=cat)

    # Add area nodes and LOCATED_IN + BELONGS_TO_CITY edges
    for spot in cleaned_spots:
        area = spot["area"]
        city = spot["city"]
        if area:
            G.add_node(f"area:{area}", type="area", name=area, parent_city=city)
            G.add_edge(f"area:{area}", f"city:{city}", relation="BELONGS_TO_CITY")

    # Add spot nodes and relationships
    for spot in cleaned_spots:
        name = spot["spot_name"]
        node_id = f"spot:{name}"

        classification = spot.get("_classification", {})

        # Add spot node (merge if exists)
        if not G.has_node(node_id):
            G.add_node(
                node_id,
                type="spot",
                name=name,
                level=spot.get("level"),
                price=spot.get("price", 0),
                category=classification.get("category", "其他"),
                sub_category=classification.get("sub_category"),
                tags=classification.get("tags", []),
                city=spot["city"],
                area=spot["area"],
            )

        # INCLUDED_IN edge to pass
        pass_node = f"pass:{spot['pass_name']}"
        G.add_edge(
            node_id,
            pass_node,
            relation="INCLUDED_IN",
            price=spot.get("price", 0),
            usage_limit=spot.get("usage_limit_raw", ""),
            notes=spot.get("notes_raw", ""),
        )

        # LOCATED_IN edge to area
        area = spot["area"]
        if area:
            G.add_edge(node_id, f"area:{area}", relation="LOCATED_IN")

        # HAS_CATEGORY edge
        cat = classification.get("category", "其他")
        G.add_edge(node_id, f"category:{cat}", relation="HAS_CATEGORY")

    # Add SAME_AS edges from alignment
    for pair in alignment_result.get("alignment_pairs", []):
        if pair.get("confirmed", False):
            n1 = f"spot:{pair['spot1']}"
            n2 = f"spot:{pair['spot2']}"
            if G.has_node(n1) and G.has_node(n2):
                G.add_edge(n1, n2, relation="SAME_AS", confidence=pair["score"])

    return G


def graph_to_json(G: nx.MultiDiGraph) -> dict:
    """Convert NetworkX graph to JSON-serializable dict."""
    nodes = []
    for node_id, attrs in G.nodes(data=True):
        node_data = {"id": node_id, **attrs}
        # Convert non-serializable types
        for k, v in node_data.items():
            if isinstance(v, set):
                node_data[k] = list(v)
        nodes.append(node_data)

    edges = []
    for u, v, key, attrs in G.edges(data=True, keys=True):
        edge_data = {"source": u, "target": v, "key": key, **attrs}
        edges.append(edge_data)

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
            "spot_count": sum(1 for _, d in G.nodes(data=True) if d.get("type") == "spot"),
            "pass_count": sum(1 for _, d in G.nodes(data=True) if d.get("type") == "pass"),
            "city_count": sum(1 for _, d in G.nodes(data=True) if d.get("type") == "city"),
            "category_count": sum(1 for _, d in G.nodes(data=True) if d.get("type") == "category"),
        },
    }


def save_graph(G: nx.MultiDiGraph, output_path: str) -> None:
    """Save graph to JSON file."""
    data = graph_to_json(G)
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_graph(input_path: str) -> nx.MultiDiGraph:
    """Load graph from JSON file."""
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    G = nx.MultiDiGraph()
    for node in data["nodes"]:
        node_id = node.pop("id")
        G.add_node(node_id, **node)

    for edge in data["edges"]:
        source = edge.pop("source")
        target = edge.pop("target")
        key = edge.pop("key", 0)
        G.add_edge(source, target, key=key, **edge)

    return G


def export_neo4j_cypher(G: nx.MultiDiGraph) -> list[str]:
    """Export graph as Neo4j Cypher statements."""
    statements = []

    # Create node constraints
    statements.append("CREATE CONSTRAINT spot_id IF NOT EXISTS FOR (n:Spot) REQUIRE n.id IS UNIQUE;")
    statements.append("CREATE CONSTRAINT pass_id IF NOT EXISTS FOR (n:Pass) REQUIRE n.id IS UNIQUE;")
    statements.append("CREATE CONSTRAINT city_id IF NOT EXISTS FOR (n:City) REQUIRE n.id IS UNIQUE;")
    statements.append("CREATE CONSTRAINT category_id IF NOT EXISTS FOR (n:Category) REQUIRE n.name IS UNIQUE;")

    # Create nodes
    for node_id, attrs in G.nodes(data=True):
        node_type = attrs.get("type", "unknown")
        if node_type == "spot":
            props = {
                "id": node_id,
                "name": attrs.get("name", ""),
                "level": attrs.get("level", ""),
                "price": attrs.get("price", 0),
                "category": attrs.get("category", ""),
                "city": attrs.get("city", ""),
                "area": attrs.get("area", ""),
            }
            props_str = ", ".join(f'{k}: "{v}"' for k, v in props.items() if v)
            statements.append(f'CREATE (s:Spot {{{props_str}}});')
        elif node_type == "pass":
            props_str = f'id: "{node_id}", name: "{attrs.get("name", "")}"'
            statements.append(f'CREATE (p:Pass {{{props_str}}});')
        elif node_type == "city":
            props_str = f'id: "{node_id}", name: "{attrs.get("name", "")}"'
            statements.append(f'CREATE (c:City {{{props_str}}});')
        elif node_type == "category":
            props_str = f'name: "{attrs.get("name", "")}"'
            statements.append(f'CREATE (cat:Category {{{props_str}}});')
        elif node_type == "area":
            props_str = f'id: "{node_id}", name: "{attrs.get("name", "")}", parent_city: "{attrs.get("parent_city", "")}"'
            statements.append(f'CREATE (a:Area {{{props_str}}});')

    return statements
