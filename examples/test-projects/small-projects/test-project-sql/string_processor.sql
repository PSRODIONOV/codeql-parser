-- string_processor.sql
-- Хранимые функции и процедуры обработки строк.
-- Аналог StringProcessor из других малых тест-проектов.

DELIMITER $$

-- Перевести строку в верхний регистр и обрезать пробелы
CREATE FUNCTION str_normalize(p_input VARCHAR(1000)) RETURNS VARCHAR(1000)
    DETERMINISTIC
BEGIN
    IF p_input IS NULL THEN
        RETURN '';
    END IF;
    RETURN UPPER(TRIM(p_input));
END$$

-- Проверить, является ли строка палиндромом
CREATE FUNCTION str_is_palindrome(p_input VARCHAR(500)) RETURNS TINYINT(1)
    DETERMINISTIC
BEGIN
    DECLARE v_cleaned VARCHAR(500);
    DECLARE v_len     INT;
    DECLARE v_left    INT DEFAULT 1;
    DECLARE v_right   INT;

    SET v_cleaned = LOWER(REGEXP_REPLACE(p_input, '[^a-zA-Z0-9]', ''));
    SET v_len     = CHAR_LENGTH(v_cleaned);
    SET v_right   = v_len;

    IF v_len = 0 THEN
        RETURN 1;
    END IF;

    WHILE v_left < v_right DO
        IF SUBSTRING(v_cleaned, v_left, 1) <> SUBSTRING(v_cleaned, v_right, 1) THEN
            RETURN 0;
        END IF;
        SET v_left  = v_left  + 1;
        SET v_right = v_right - 1;
    END WHILE;

    RETURN 1;
END$$

-- Подсчитать количество вхождений подстроки
CREATE FUNCTION str_count_occurrences(p_text VARCHAR(4000),
                                      p_sub  VARCHAR(500)) RETURNS INT
    DETERMINISTIC
BEGIN
    DECLARE v_count  INT DEFAULT 0;
    DECLARE v_pos    INT DEFAULT 1;
    DECLARE v_sublen INT;

    IF p_sub IS NULL OR p_sub = '' THEN
        RETURN 0;
    END IF;

    SET v_sublen = CHAR_LENGTH(p_sub);

    WHILE v_pos <= CHAR_LENGTH(p_text) DO
        IF LOCATE(p_sub, p_text, v_pos) = v_pos THEN
            SET v_count = v_count + 1;
            SET v_pos   = v_pos + v_sublen;
        ELSE
            SET v_pos = v_pos + 1;
        END IF;
    END WHILE;

    RETURN v_count;
END$$

-- Обернуть строку, добавив префикс/суффикс
CREATE FUNCTION str_wrap(p_input  VARCHAR(1000),
                         p_prefix VARCHAR(100),
                         p_suffix VARCHAR(100)) RETURNS VARCHAR(1200)
    DETERMINISTIC
BEGIN
    IF p_input IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN CONCAT(IFNULL(p_prefix, ''), p_input, IFNULL(p_suffix, ''));
END$$

-- Записать строку в хранилище с нормализацией
CREATE PROCEDURE str_store_normalized(IN p_filename VARCHAR(255),
                                      IN p_content  VARCHAR(4000))
BEGIN
    DECLARE v_normalized VARCHAR(4000);
    SET v_normalized = str_normalize(p_content);
    CALL storage_write(p_filename, v_normalized);
END$$

-- Поиск строки по шаблону в хранилище (LIKE)
CREATE PROCEDURE str_search_in_storage(IN p_pattern VARCHAR(255))
BEGIN
    SELECT filename, size_bytes
    FROM file_records
    WHERE content LIKE p_pattern AND is_deleted = 0
    ORDER BY filename;
END$$

-- Представление: файлы с длинным содержимым
CREATE VIEW large_text_files AS
    SELECT filename, size_bytes, created_at
    FROM file_records
    WHERE size_bytes > 1024 AND is_deleted = 0$$

DELIMITER ;
