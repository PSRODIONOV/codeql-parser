import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;

/** Драйвер для H2: in-memory БД + набор SQL, задействует парсер/исполнение/хранилище. */
public class H2Driver {
    public static void main(String[] args) throws Exception {
        Class.forName("org.h2.Driver");
        try (Connection c = DriverManager.getConnection("jdbc:h2:mem:test;DB_CLOSE_DELAY=-1")) {
            try (Statement s = c.createStatement()) {
                s.execute("CREATE TABLE users(id INT PRIMARY KEY AUTO_INCREMENT, "
                        + "name VARCHAR(100), age INT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)");
                s.execute("CREATE INDEX idx_name ON users(name)");
                for (int i = 1; i <= 20; i++) {
                    s.execute("INSERT INTO users(name, age) VALUES ('user" + i + "', " + (18 + i) + ")");
                }
                ResultSet rs = s.executeQuery(
                        "SELECT name, age FROM users WHERE age > 25 ORDER BY age DESC LIMIT 5");
                int n = 0;
                while (rs.next()) { n++; rs.getString(1); rs.getInt(2); }
                System.out.println("selected rows: " + n);

                s.execute("UPDATE users SET age = age + 1 WHERE id <= 10");
                s.execute("DELETE FROM users WHERE age > 35");

                rs = s.executeQuery("SELECT COUNT(*), AVG(age), MIN(age), MAX(age) FROM users");
                rs.next();
                System.out.println("count=" + rs.getInt(1) + " avg=" + rs.getInt(2));

                // соединение, группировка
                s.execute("CREATE TABLE orders(id INT, uid INT, amount DECIMAL(10,2))");
                s.execute("INSERT INTO orders VALUES (1,1,10.5),(2,1,20.0),(3,2,5.0)");
                rs = s.executeQuery("SELECT u.name, SUM(o.amount) FROM users u "
                        + "JOIN orders o ON u.id = o.uid GROUP BY u.name HAVING SUM(o.amount) > 1");
                while (rs.next()) { rs.getString(1); }

                // транзакция с откатом
                c.setAutoCommit(false);
                s.execute("INSERT INTO users(name, age) VALUES ('temp', 99)");
                c.rollback();
                c.setAutoCommit(true);
            }
        }
        System.out.println("H2 driver: OK");
    }
}
