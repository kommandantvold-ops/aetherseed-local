"""Her trust levels: one ladder, one place.

how the trust levels should be consolidated -
"today reader=writer and collaborator=autonomous give the same tools, and the
network tier is never on" - chose: **4 levels**.

    level        points  tool tiers  what it opens
    observer          0  1           read: list, read, search, her health and trust
    writer           50  1, 2        + notes and the to-do list (sandboxed writes)
    builder         500  1, 2, 3     + calculate, count, compare - exact, by the unit
    autonomous     2000  1, 2, 3, 4  reserved: nothing more today (no network tool
                                     is on; nothing leaves the unit)

Until this step there were six. Two pairs opened the same tools: reader and
writer, and collaborator and autonomous ([1, 2, 3,
4], where tier 4 is network and network is off on every unit). Each step now
opens something real, except the top, which is kept for tools that do not
exist yet.

The thresholds are the old ones where a level kept its tools: writing opens
at 50, as it did for reader; exact tools at 500. A unit's level is read from
its standing, so nothing stored needs rewriting: a unit at 1002 points was a
collaborator and is a builder, with the same tools.

Names written before this step - in training summaries, trust events,
approvals, a unit's config - are read through canonical: reader is writer,
collaborator is builder.
"""

LADDER = ("observer", "writer", "builder", "autonomous")

POINTS = {"observer": 0, "writer": 50, "builder": 500, "autonomous": 2000}

PERMISSIONS = {
    "observer": [1],               # read only
    "writer": [1, 2],              # + sandboxed writes: notes, the to-do list
    "builder": [1, 2, 3],          # + the exact tools: calculate, count, compare
    "autonomous": [1, 2, 3, 4],    # reserved; tier 4 (network) is off on every unit
}

# The plant names of the growth line, one per level.
NAMES = {"observer": ("Seed", "🌰"), "writer": ("Sprout", "🌱"),
         "builder": ("Tree", "🌳"), "autonomous": ("Bee", "🐝")}

LEGACY = {"reader": "writer", "collaborator": "builder", "sapling": "writer",
          "flowering": "builder"}


def canonical(level):
    """A level as this build names it - an old name read as its new one.
    Anything else is returned as it came (lower-cased), for the caller to
    refuse."""
    if not isinstance(level, str):
        return level
    lv = level.strip().lower()
    return LEGACY.get(lv, lv)
