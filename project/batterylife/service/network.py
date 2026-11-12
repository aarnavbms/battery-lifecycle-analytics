"""Network analysis of the passport ecosystem.

Every signed passport event is an interaction: an actor did something to a
battery. Two networks are built from the events:

  hand-off network   directed, actor -> actor. An edge A -> B is added each time
                     B signs the event that follows one signed by A on the same
                     battery (custody or responsibility passes from A to B).
  process network    directed, event type -> event type, counting how often one
                     lifecycle step is followed by another (a process map).

Standard measures are reported for each node: weighted in- and out-degree,
betweenness centrality and PageRank; and for each graph: density and
reciprocity. An actor-battery (two-mode) table shows how many batteries and
events each actor touched.
"""
from __future__ import annotations

import math
from collections import Counter

import networkx as nx

from ..passport.schema import EVENT_TYPES, ROLES
from . import db

ROLE_ORDER = ["manufacturer", "oem", "bms", "assessor", "repurposer", "recycler"]
EVENT_ORDER = list(EVENT_TYPES)


def _ring(names: list[str], radius: float = 1.0) -> dict:
    n = max(len(names), 1)
    return {name: (round(radius * math.sin(2 * math.pi * k / n), 4), round(radius * math.cos(2 * math.pi * k / n), 4))
            for k, name in enumerate(names)}


def _measures(g: nx.DiGraph) -> dict:
    if g.number_of_nodes() == 0:
        return {}
    btw = nx.betweenness_centrality(g, normalized=True)
    pr = nx.pagerank(g, weight="weight") if g.number_of_edges() else {n: 0.0 for n in g}
    return {n: {"in": int(g.in_degree(n, weight="weight")), "out": int(g.out_degree(n, weight="weight")),
                "betweenness": round(btw[n], 4), "pagerank": round(pr[n], 4)} for n in g}


def _graph_stats(g: nx.DiGraph) -> dict:
    n = g.number_of_nodes()
    return {"nodes": n, "edges": g.number_of_edges(), "total_weight": int(sum(d["weight"] for *_, d in g.edges(data=True))),
            "density": round(nx.density(g), 4) if n > 1 else 0.0,
            "reciprocity": round(nx.reciprocity(g), 4) if g.number_of_edges() else 0.0}


def build(conn, include_uploads: bool = False) -> dict:
    origins = ("lab", "hardware", "upload") if include_uploads else ("lab", "hardware")
    actors = {a["actor_id"]: dict(a) for a in conn.execute("SELECT actor_id, name, role FROM actors")}
    q = ("SELECT e.passport_id, e.idx, e.type, e.actor_id FROM events e JOIN passports p USING (passport_id) "
         f"WHERE p.origin IN ({','.join('?' * len(origins))}) ORDER BY e.passport_id, e.idx")
    events = db.rows(conn.execute(q, origins))

    hand, proc = nx.DiGraph(), nx.DiGraph()
    touched: dict[str, set] = {}
    n_events = Counter()
    paths = Counter()
    by_passport: dict[str, list] = {}
    for e in events:
        by_passport.setdefault(e["passport_id"], []).append(e)
    for pid, evs in by_passport.items():
        steps = []
        for k, e in enumerate(evs):
            touched.setdefault(e["actor_id"], set()).add(pid)
            n_events[e["actor_id"]] += 1
            hand.add_node(e["actor_id"]); proc.add_node(e["type"])
            if not steps or steps[-1] != e["type"]:
                steps.append(e["type"])
            if k:
                prev = evs[k - 1]
                if prev["actor_id"] != e["actor_id"]:
                    w = hand.get_edge_data(prev["actor_id"], e["actor_id"], {"weight": 0})["weight"]
                    hand.add_edge(prev["actor_id"], e["actor_id"], weight=w + 1)
                if prev["type"] != e["type"]:
                    w = proc.get_edge_data(prev["type"], e["type"], {"weight": 0})["weight"]
                    proc.add_edge(prev["type"], e["type"], weight=w + 1)
        milestones = [s for s in steps if s not in ("SOH_ASSESSMENT", "RUL_PREDICTION", "CARBON_FOOTPRINT_DECLARED")]
        paths[" > ".join(milestones)] += 1

    for aid in actors:                      # registered actors that never signed stay visible as isolates
        if "-LOCAL-" not in aid or aid in touched:
            hand.add_node(aid)
    order = sorted(hand.nodes, key=lambda a: (ROLE_ORDER.index(actors[a]["role"]) if actors.get(a, {}).get("role") in ROLE_ORDER else 99, a))
    pos_a = _ring(order)
    ev_order = [t for t in EVENT_ORDER if t in proc]
    pos_e = _ring(ev_order)
    ma, me = _measures(hand), _measures(proc)

    def pack(g, pos, measures, label):
        return {"nodes": [{"id": n, "x": pos[n][0], "y": pos[n][1], **label(n), **measures[n]} for n in pos],
                "edges": [{"source": u, "target": v, "weight": d["weight"]} for u, v, d in g.edges(data=True)],
                "stats": _graph_stats(g)}

    handoff = pack(hand, pos_a, ma, lambda n: {"name": actors.get(n, {}).get("name", n),
                                               "role": actors.get(n, {}).get("role", "unknown"),
                                               "batteries": len(touched.get(n, ())), "events": n_events[n]})
    process = pack(proc, pos_e, me, lambda n: {"name": n.replace("_", " ").capitalize().replace("Soh", "SOH").replace("Rul", "RUL"),
                                               "access": EVENT_TYPES[n][1], "roles": sorted(EVENT_TYPES[n][0])})
    top_b = max(ma, key=lambda n: ma[n]["betweenness"]) if ma else None
    top_p = max(ma, key=lambda n: ma[n]["pagerank"]) if ma else None
    hub = max(me, key=lambda n: me[n]["in"] + me[n]["out"]) if me else None
    return {
        "passports": len(by_passport), "events": len(events), "actors": len(order),
        "roles": {r: ROLES[r] for r in ROLE_ORDER},
        "handoff": handoff, "process": process,
        "paths": [{"path": p, "batteries": c} for p, c in paths.most_common()],
        "findings": {"broker": top_b, "broker_name": actors.get(top_b, {}).get("name"),
                     "broker_betweenness": ma[top_b]["betweenness"] if top_b else None,
                     "most_central": top_p, "most_central_name": actors.get(top_p, {}).get("name"),
                     "process_hub": hub},
        "include_uploads": include_uploads,
    }
