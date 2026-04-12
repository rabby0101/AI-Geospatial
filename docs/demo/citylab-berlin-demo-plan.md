# CityLab Berlin Demo Plan — Cognitive Geospatial Agent

## Context

**Venue:** CityLab Berlin, Platz der Luftbrücke 4, Tempelhof
**Audience:** Smart city enthusiasts, urban planners, open data advocates, civic tech people, policy makers
**Goal:** Showcase / Inspire — "Here's what's possible with AI + open geospatial data"
**Format:** Intimate room, big screen, 1 hour, conversational tone

**Core thesis:** "Every question a city planner asks every day can now be answered by an agent that reasons, plans, and recovers — like a specialist on call, 24/7, for free."

---

## Narrative Arc

**Act I — The Problem (0–10 min):** Cities drown in geospatial data. The people who most need it can't access it without a GIS specialist. Show the gap, make it personal, reveal the solution.

**Act II — The Demo (10–50 min):** Five escalating chapters. The audience shifts from "that's handy" → "that's remarkable" → "how is it fixing its own mistakes?" → "this changes what's possible."

**Act III — The Bigger Picture (50–60 min):** How it works, what data it uses, who it's for. Open invitation for questions and collaboration.

---

## Time Breakdown

| Time | Section |
|---|---|
| 0:00–2:00 | Cold open / hook (no slides) |
| 2:00–8:00 | The problem setup |
| 8:00–12:00 | App introduction + The Reasoning Agent reveal |
| 12:00–20:00 | Chapter 1: Neighborhood Explorer |
| 20:00–28:00 | Chapter 2: Business Site Selection + BauNVO |
| 28:00–35:00 | Chapter 3: Routing and Accessibility |
| 35:00–43:00 | Chapter 4: The Self-Correcting Agent |
| 43:00–50:00 | Chapter 5: Grand Synthesis (the finale) |
| 50:00–55:00 | Behind the scenes |
| 55:00–58:00 | Target users and real-world cases |
| 58:00–60:00 | Close + open floor |

---

## Cold Open (0:00–2:00)

Open with a question, no slides:

> "Raise your hand if you've ever wanted to know something about your neighborhood — which streets have the worst air quality, where the nearest green space is, whether a new café could legally open on your block — and had absolutely no idea how to find out, even though that data definitely exists somewhere."

Most hands go up. "That's the problem we're going to solve in the next hour."

---

## Problem Setup (2:00–8:00)

Key talking points:
- Berlin has extraordinary open data. ODIS has catalogued hundreds of datasets. OSM coverage is world-class.
- The people who most need this — community organizers, small business owners, local councillors — have no way to query it. GIS tools require years of training. APIs require programming. Consultants cost money and take weeks.
- This is not a data scarcity problem. It's an access problem.

> "What if you could just ask — and something actually smart figured out the answer for you?"

---

## App Introduction + The Reasoning Agent Reveal (8:00–12:00)

> "This is the Cognitive Geospatial Agent. It takes a question in plain German or English and answers it using open Berlin data. But it's not a search engine. It's an agent — it reasons about your question, decides what data it needs, designs a query, runs it, and checks whether the result makes sense."

Open the interface. Make sure the **agent reasoning panel is visible** on the big screen.

Type, slowly:

> "How many schools are there in Friedrichshain-Kreuzberg?"

**Do not narrate while it runs.** Let the audience watch the agent panel. Let the silence work.

After the answer appears:

> "Let me tell you what just happened. The agent didn't have the answer pre-loaded. It first asked: what table in the database contains schools? It found the answer. Then it asked: does that table have a district column, or do I need a spatial join? It figured that out. Then it wrote a PostGIS query, ran it against the real Berlin dataset, and gave you a number. Every step is there on the right side of the screen."

> "That wasn't a lookup. That was an agent. You just watched it think."

---

## Chapter 1: Neighborhood Explorer (12:00–20:00)

**Skill: Spatial Analysis | Theme: Simple, immediate, delightful**

The audience now understands the agent flow. Run these at normal speed — they're warming up, not just seeing results.

**Query 1.1 — The Warmup**
> "Show me all parks in Neukölln larger than 5 hectares."

Why: Neukölln is emotionally loaded. Parks are universally understood. Result appears as green polygons in seconds. Audience is comfortable now — they've seen the agent think once. Let this one land visually.

**Query 1.2 — Civic meaning**
> "How many playgrounds are within 500 meters of the Neukölln Rathaus?"

Why: Introduces spatial buffers without saying "buffer." The agent geocodes the Rathaus, creates a buffer, then counts playgrounds within it — three tool calls, visible in the panel. Previously required a GIS technician and a Jira ticket.

**Query 1.3 — First surprise**
> "Which Bezirk in Berlin has the highest density of community gardens per square kilometer?"

Why: Crosses district boundaries, requires aggregation across all 12 Bezirke. The answer usually surprises people and triggers conversation. Let the audience react before moving on.

Bridge: "Simple. Now let's add law."

---

## Chapter 2: Business Site Selection + BauNVO (20:00–28:00)

**Skill: Business Analyst | Theme: Legal intelligence meets spatial analysis**

Set the scene verbally:

> "Imagine you're opening a small bakery in Berlin. You need a location where zoning law allows food retail, foot traffic is high, and you're not surrounded by three other bakeries."

**Query 2.1 — The legal layer**
> "Where in Mitte are there commercial zones under BauNVO that permit food retail businesses?"

Why: The agent is reasoning over German zoning law encoded as a knowledge graph. Say:

> "It just consulted the Baunutzungsverordnung — the federal building use ordinance. Not because we pre-filtered for bakeries. Because the agent knows what BauNVO says about food retail, and it can match that against the spatial zoning data."

Watch faces change.

**Query 2.2 — Competition analysis**
> "Show me all existing cafés and bakeries within 300 meters of those zones."

Why: Layers competitor context on top of legal permissibility. The map shows opportunity and threat simultaneously. The agent chains results from the previous step without being asked to.

**Query 2.3 — The MCDA moment**
> "Score these locations for a new bakery considering foot traffic from nearby transit stops, distance from competitors, and permitted use under zoning law."

Why: Multi-Criteria Decision Analysis fires. Polygons colored by suitability score. Say:

> "This used to take a consultant two weeks and cost ten thousand euros. We just did it in forty seconds, using only open data, for free."

Pause. Let it land.

Bridge: "Now let's add people."

---

## Chapter 3: Routing and Accessibility (28:00–35:00)

**Skill: Routing Expert | Theme: Who can reach what — the equity angle**

This chapter shifts register. It's not about business — it's about people.

**Query 3.1 — Simple routing**
> "What is the walking route from Görlitzer Park to the nearest pediatric clinic?"

Why: Concrete, human, easy to visualize. The agent calls the routing tool with the right mode and waypoints — no instruction needed. Mention Valhalla and OpenStreetMap — nothing proprietary.

**Query 3.2 — Isochrone (the visual power move)**
> "Show me everywhere reachable by bicycle within 15 minutes from Alexanderplatz."

Why: Isochrones are visually dramatic — a polygon radiates across the city. The agent knows to use `walking_isochrone` rather than a straight-line buffer, because it's been trained on road-network accuracy.

> "Your commute range, visualized. Planners recognize this as a standard accessibility tool — now available in plain English."

**Query 3.3 — The equity question**
> "Which neighborhoods in Berlin have the lowest density of pharmacies accessible within 10 minutes on foot?"

Why: Accessibility gap analysis. The map highlights underserved areas. Policy people lean forward here. This is not abstract — it identifies real places where real people are underserved.

Bridge: "Now let's show you something the previous generation of AI assistants couldn't do."

---

## Chapter 4: The Self-Correcting Agent (35:00–43:00)

**Theme: Trust — "It doesn't just answer, it adapts when it's wrong."**

> "Every system we've built has a failure mode. The old way of doing this — a fixed pipeline that generates one query and runs it — breaks silently. You get an empty result or an error and you have no idea why. Agent mode is different. When it hits a dead end, it doesn't stop. Watch."

**Query 4.1 — The recovery moment**
> "Show me all buildings in Berlin suitable for community use."

Why: Deliberately ambiguous. "Community use" isn't a column name — the agent has to reason about what that means, try schema discovery, possibly try multiple table or column combinations, and self-correct when it gets zero results.

Open the agent panel wide on the big screen. When the agent hits a step where it tried a query and got back nothing — point to it:

> "Stop here. The agent ran a query and got zero results. It knows that's suspicious. Watch what it does in the next thought."

When it recovers:

> "It recognized its own mistake. It tried a different column, a different filter. No error message to you. No starting over. It just adapted. You can see the exact moment it changed its mind."

**Query 4.2 — Multi-hop orchestration**
> "For each of Berlin's districts, what's the average distance to the nearest hospital?"

Why: Forces the agent to chain 4–5 tool calls: find district geometries → find hospital table → compute ST_Distance for each district centroid → aggregate by district. Audience watches the reasoning panel tick through steps.

> "That's five distinct operations. A different table lookup, a distance calculation, a spatial join, an aggregation. It planned all of it from one sentence."

**Query 4.3 — The live volunteer**

> "I want to try something unrehearsed."

Ask one person in the audience for a question about a specific neighborhood they know personally — somewhere they live or work. Run it live. Don't pre-screen it.

If it works: say nothing. Let the result speak.

If it struggles: narrate the recovery. This is actually *better* — the audience watches the agent adapt in real time to an edge case.

Bridge: "This is the version where you stop worrying about what the AI can't do — and start wondering what question you haven't thought to ask yet."

---

## Chapter 5: Grand Synthesis (43:00–50:00)

**Skills: All | Theme: Everything at once**

> "I want to show you what this system can do when you stop thinking in single questions and start thinking in problems."

> "I'm going to let you watch this one run fully — every thought, every tool call. I won't narrate until it finishes."

**The Grand Query:**
> "I'm advising the Berlin Senate on where to locate new climate-resilient community centers in the next five years. Find areas in Berlin that have high population density, low green space coverage, poor transit accessibility, and where zoning law permits public community facilities. Score the top candidate locations."

Let the query run in silence. The audience reads the agent panel.

As steps fire, you can narrate quietly without interrupting:
- When BauNVO is queried: *"There — it's checking the zoning law."*
- When Valhalla fires: *"Road-network accessibility, not straight-line estimates."*
- When MCDA scores appear: *"It's weighing four criteria simultaneously."*

When results appear:

> "That question — answered that way, with that combination of legal, spatial, and demographic data, using an agent that planned its own approach from scratch — did not exist as a capability a year ago. It does now. And it's built entirely on open data."

---

## Behind the Scenes (50:00–55:00)

### The ReAct Loop — How the Agent Thinks

> "The classic query mode was a six-specialist assembly line — each step handed off to the next. Agent mode is different. It's a loop."

> "Think → Act → Observe → repeat. The agent generates a thought, picks a tool, sees the result, then decides what to do next. Up to forty cycles per query. And if it hits a dead end — wrong table, empty result, malformed output — it doesn't hand it back to you. It tries another way."

> "That's the self-correction you saw in Chapter 4. It's not magic. It's a loop that includes the error as input."

The agent has ten tools it can call in any order:
- **Geocoding** — converts place names to coordinates
- **Buffer creation** — draws a radius around a point
- **Schema discovery** — learns what tables and columns exist in the database
- **SQL execution** — runs PostGIS spatial queries against the real Berlin dataset
- **Spatial filtering** — clips results to a boundary
- **Routing** — computes road-network paths via Valhalla
- **Isochrones** — computes reachable areas by mode and time
- **MCDA scoring** — ranks locations by multiple weighted criteria

### BauNVO Knowledge Graph — The Legal Brain

> "German zoning law — the Baunutzungsverordnung — defines what you can build or operate in every zone type. WA is residential. MI is mixed use. GE is industrial. We've encoded all of that into a knowledge graph — a structured network of legal relationships. When you ask 'where can I open a bakery,' the agent reasons over the legal rules first, then intersects that with spatial data."

### The Open Data Stack — A Civic Achievement

> "Everything this system uses is free, open, and maintained by the public:
>
> - **OpenStreetMap** — 24 Berlin datasets, from streets to green spaces, maintained by volunteers
> - **Valhalla** — open-source routing engine, road-network accurate
> - **Nominatim** — open-source geocoding
>
> Total cost of the underlying data: zero euros. If the public paid for the infrastructure that generates this data — the roads, the district boundaries, the street network — the public should be able to use it."

---

## Target Users (55:00–58:00)

| User | Use Case |
|---|---|
| Urban Planners (Bezirk offices) | Accessibility audits, zoning reviews, infrastructure gap analysis |
| Community Organizations | Evidence for park/street/facility proposals using public spatial data |
| Small Business Owners | Location scouting with zoning compliance + competition analysis |
| Senate Policy Departments | Multi-dataset synthesis for infrastructure investment priorities |
| Journalists | Civic data reporting on urban inequality, development patterns |
| Researchers | Reproducible spatial queries against open Berlin datasets |

---

## The Close (58:00–60:00)

> "We built this with a laptop, open data, and a conviction that the city's spatial intelligence should belong to everyone who lives in it — not just to those who can afford a GIS consultant or wait a week for an answer."

Then open the floor.

---

## Tips for the Live Demo

### Preparation
- Run every query the morning of the event — including Query 4.1 (self-correction) to confirm the agent panel shows a visible recovery step
- Pre-load the map centered on Berlin with Bezirke visible as people enter
- Use large, readable font in the query input (audience reading on big screen)
- Connect via ethernet, not conference WiFi (LLM API calls are the bottleneck)
- Confirm the agent reasoning panel is visible and readable at presentation font size

### Pacing
- Type queries slowly and deliberately — audience is reading as you type
- After each result loads, pause 3–5 seconds before speaking
- During Chapter 4 Query 4.1, **slow down deliberately** — the self-correction moment is the demo's emotional peak
- When the Grand Synthesis query runs, stay silent. Let the audience read. Resist the urge to fill space.

### Audience Engagement
- End of Chapter 1: ask if anyone wants to suggest a neighborhood for the next query
- Chapter 4 Query 4.3 is your planned unrehearsed moment — embrace it
- Watch for the moment someone reaches for their phone camera — pause and let them capture it

---

## Handling Failures

| Failure | Response |
|---|---|
| LLM API timeout | Switch to Gemini: "Let me show you the multi-LLM fallback — this is actually a feature." |
| Query returns no results | "That's useful — it means there are no matching records, which is itself a finding. Let me refine." Then demonstrate refinement. |
| Agent runs too many steps / hangs | "It's thinking deeply about this — which is actually what we want. Let me walk you through what it's doing." Narrate the agent panel aloud. |
| Valhalla routing timeout | "While it calculates — let me show you a previous isochrone result." |
| Whole app down | Narrate live over pre-recorded screen capture video |
| Question you can't answer | "I don't know — but this is open source and that's a genuinely interesting research question. Let's note it." Never bluff. |

---

## Pre-Event Checklist

- [ ] Run all 12 demo queries and screenshot every result the morning of the event
- [ ] Confirm Query 4.1 (community buildings) produces a visible agent self-correction step — if not, have a backup query ready that demonstrates recovery
- [ ] Export a 12-minute screen recording of the full demo as backup video
- [ ] Test Ollama offline mode is loaded with a capable model
- [ ] Confirm PostGIS has Berlin OSM datasets loaded and indexed
- [ ] Confirm the agent reasoning panel is readable at full-screen size on the venue display
- [ ] Test from the venue's network (not home network)
- [ ] Bring your own HDMI adapter
- [ ] Have the GitHub repository URL ready to share on the final slide
- [ ] Have your contact details on the final slide
- [ ] Pre-load a warm, visually appealing map (Berlin Bezirke boundaries) as people enter
