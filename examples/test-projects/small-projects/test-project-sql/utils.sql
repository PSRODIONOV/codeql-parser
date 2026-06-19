-- utils.sql
-- Вспомогательные математические функции.
-- Аналог utils из других малых тест-проектов.

DELIMITER $$

-- Факториал (рекурсивный)
CREATE FUNCTION util_factorial(p_n INT) RETURNS BIGINT
    DETERMINISTIC
BEGIN
    IF p_n < 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'factorial: n must be non-negative';
    END IF;
    IF p_n <= 1 THEN
        RETURN 1;
    END IF;
    RETURN p_n * util_factorial(p_n - 1);
END$$

-- Чётность числа
CREATE FUNCTION util_is_even(p_n BIGINT) RETURNS TINYINT(1)
    DETERMINISTIC
BEGIN
    RETURN IF(p_n MOD 2 = 0, 1, 0);
END$$

-- Сумма массива чисел (через таблицу)
CREATE PROCEDURE util_sum_array(IN p_values TEXT, OUT p_total BIGINT)
BEGIN
    DECLARE v_pos   INT    DEFAULT 1;
    DECLARE v_delim VARCHAR(1) DEFAULT ',';
    DECLARE v_token VARCHAR(50);
    DECLARE v_total BIGINT DEFAULT 0;
    DECLARE v_len   INT;

    SET v_len = CHAR_LENGTH(p_values);

    -- Итерация по CSV-строке
    WHILE v_pos <= v_len DO
        SET v_token = SUBSTRING_INDEX(SUBSTRING(p_values, v_pos), v_delim, 1);
        SET v_total = v_total + CAST(v_token AS SIGNED);
        SET v_pos   = v_pos + CHAR_LENGTH(v_token) + 1;
    END WHILE;

    SET p_total = v_total;
END$$

-- Простое число
CREATE FUNCTION util_is_prime(p_n BIGINT) RETURNS TINYINT(1)
    DETERMINISTIC
BEGIN
    DECLARE v_i BIGINT DEFAULT 5;

    IF p_n <= 1 THEN RETURN 0; END IF;
    IF p_n <= 3 THEN RETURN 1; END IF;
    IF p_n MOD 2 = 0 OR p_n MOD 3 = 0 THEN RETURN 0; END IF;

    WHILE v_i * v_i <= p_n DO
        IF p_n MOD v_i = 0 OR p_n MOD (v_i + 2) = 0 THEN
            RETURN 0;
        END IF;
        SET v_i = v_i + 6;
    END WHILE;

    RETURN 1;
END$$

-- Наибольший общий делитель (алгоритм Евклида)
CREATE FUNCTION util_gcd(p_a BIGINT, p_b BIGINT) RETURNS BIGINT
    DETERMINISTIC
BEGIN
    DECLARE v_a BIGINT DEFAULT p_a;
    DECLARE v_b BIGINT DEFAULT p_b;
    DECLARE v_t BIGINT;

    WHILE v_b <> 0 DO
        SET v_t = v_b;
        SET v_b = v_a MOD v_b;
        SET v_a = v_t;
    END WHILE;

    RETURN v_a;
END$$

-- Избыточная утилита — объявлена, но нигде не вызывается
CREATE PROCEDURE util_unused()
BEGIN
    DECLARE v_local_in_unused INT DEFAULT 0;
    SET v_local_in_unused = v_local_in_unused + 1;
END$$

DELIMITER ;
