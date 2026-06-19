import sqlite3
con = sqlite3.connect('workspace/test-php/project.db')
total = con.execute('SELECT COUNT(*) FROM q_control').fetchone()[0]
unresolved = con.execute("SELECT COUNT(*) FROM q_control WHERE callee_name LIKE '<unresolved%'").fetchone()[0]
print(f'total control rows: {total}')
print(f'still unresolved: {unresolved}')
store = con.execute("SELECT caller_name, callee_name FROM q_control WHERE callee_name LIKE '%storeResult%'").fetchall()
print('storeResult:', store)
parent = con.execute("SELECT caller_name, callee_name FROM q_control WHERE callee_name LIKE 'parent%'").fetchall()
print('parent calls:', parent)
calc = con.execute("SELECT caller_name, callee_name FROM q_control WHERE caller_name='Calculator.add'").fetchall()
print('Calculator.add:', calc)
con.close()
