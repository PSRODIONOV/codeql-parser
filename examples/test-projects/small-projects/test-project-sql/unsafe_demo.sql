-- unsafe_demo.sql
-- Демонстрация потенциально опасных конструкций (ПОК).
-- Модуль намеренно содержит опасные паттерны разных CWE-категорий.
-- Аналог unsafe_demo из других малых тест-проектов.

DELIMITER $$

-- CWE-89: динамический SQL через EXECUTE(@sql) — SQL-инъекция
CREATE PROCEDURE unsafe_dynamic_query(IN p_table_name VARCHAR(100),
                                      IN p_condition  VARCHAR(500))
BEGIN
    DECLARE v_sql TEXT;
    -- Прямая конкатенация пользовательского ввода — уязвимость SQL-инъекции
    SET v_sql = CONCAT('SELECT * FROM ', p_table_name,
                       ' WHERE ', p_condition);
    SET @unsafe_sql = v_sql;
    -- CWE-89: EXECUTE с динамически построенной строкой
    PREPARE unsafe_stmt FROM @unsafe_sql;
    EXECUTE unsafe_stmt;
    DEALLOCATE PREPARE unsafe_stmt;
END$$

-- CWE-89: sp_executesql-подобный вызов (T-SQL паттерн, для демонстрации)
CREATE PROCEDURE unsafe_exec_string(IN p_user_input VARCHAR(1000))
BEGIN
    DECLARE v_sql VARCHAR(2000);
    SET v_sql = p_user_input;
    SET @unsafe_exec = v_sql;
    -- Имитация EXEC(@sql) - CWE-89
    PREPARE stmt_exec FROM @unsafe_exec;
    EXECUTE stmt_exec;
    DEALLOCATE PREPARE stmt_exec;
END$$

-- CWE-798: жёстко заданный пароль в коде
CREATE PROCEDURE unsafe_hardcoded_creds()
BEGIN
    DECLARE v_admin_password VARCHAR(100);
    -- CWE-798: хранение пароля в открытом виде
    SET v_admin_password = 'admin123secret';
    -- Сравнение с хардкодным паролем
    UPDATE users SET PASSWORD = 'admin123secret' WHERE id = 1;
END$$

-- CWE-269: избыточные привилегии
CREATE PROCEDURE unsafe_grant_all(IN p_user VARCHAR(100))
BEGIN
    -- CWE-269: выдача всех привилегий
    -- GRANT ALL ON *.* TO p_user; -- (закомментировано, но паттерн присутствует)
    SET @grant_stmt = CONCAT('GRANT ALL ON *.* TO ''', p_user, '''');
    PREPARE grant_exec FROM @grant_stmt;
    EXECUTE grant_exec;
    DEALLOCATE PREPARE grant_exec;
END$$

-- CWE-400: опасный TRUNCATE внутри процедуры
CREATE PROCEDURE unsafe_truncate_log()
BEGIN
    -- CWE-400: безвозвратное уничтожение данных
    TRUNCATE TABLE file_access_log;
    -- Также обнуляем счётчик обращений
    CALL counter_reset('access_count');
END$$

-- Безопасная альтернатива: параметризованный запрос с проверкой
CREATE PROCEDURE safe_query_by_id(IN p_id INT)
BEGIN
    DECLARE v_name VARCHAR(100);
    -- Правильно: параметр передан напрямую (не конкатенацией)
    IF p_id <= 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'id must be positive';
    END IF;
    SELECT name INTO v_name FROM animals WHERE id = p_id;
    SELECT v_name AS result;
END$$

DELIMITER ;
