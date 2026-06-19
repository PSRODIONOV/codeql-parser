import sqlite3
con = sqlite3.connect("workspace/test-php/project.db")

rows = con.execute(
    "SELECT caller_name, callee_name FROM q_control "
    "WHERE callee_name LIKE '%Iterator%' "
    "   OR callee_name LIKE '%encaps%' "
    "   OR callee_name LIKE '%unresolved%'"
).fetchall()
print("Artifacts/unresolved remaining:", len(rows))
for r in rows:
    print(" ", r)

total = con.execute("SELECT COUNT(*) FROM q_control").fetchone()[0]
print("Total control rows:", total)

print()
rows2 = con.execute(
    "SELECT caller_name, callee_name FROM q_control ORDER BY caller_name, callee_name"
).fetchall()
print("Sample resolved calls:")
for r in rows2[:10]:
    print(" ", r)
