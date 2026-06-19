-- main.sql
-- Главная процедура-оркестратор — точка входа тест-проекта.
-- Аналог main из других малых тест-проектов.

DELIMITER $$

-- Инициализация всей схемы (вызывается один раз при развёртывании)
CREATE PROCEDURE main_init()
BEGIN
    -- Счётчики
    CALL counter_create('files_total',   1);
    CALL counter_create('ops_total',     1);
    CALL counter_create('errors_total',  1);

    -- Начальное состояние калькулятора
    CALL calc_store_result(0);
END$$

-- Демонстрация калькулятора
CREATE PROCEDURE main_demo_calculator()
BEGIN
    DECLARE v_result DECIMAL(18,6);
    DECLARE v_power  DECIMAL(18,6);

    CALL calc_add(10, 5,    v_result);  -- 15
    CALL calc_mul(v_result, 2, v_result); -- 30
    CALL calc_div(v_result, 4, v_result); -- 7.5
    CALL calc_power(2, 8,   v_power);   -- 256
    CALL calc_mod(17, 5,    v_result);  -- 2
    CALL counter_increment('ops_total');
END$$

-- Демонстрация хранилища файлов
CREATE PROCEDURE main_demo_storage()
BEGIN
    DECLARE v_content MEDIUMTEXT;
    DECLARE v_size    INT;

    CALL storage_write('hello.txt', 'Hello, SQL World!');
    CALL storage_write('data.csv',  'id,name,value\n1,foo,42\n2,bar,99');

    -- Прочитать и проверить размер
    SET v_size = storage_size('hello.txt');
    IF v_size <= 0 THEN
        CALL counter_increment('errors_total');
    ELSE
        CALL counter_increment('ops_total');
    END IF;

    -- Нормализованная запись через str_store_normalized
    CALL str_store_normalized('upper.txt', 'mixed CASE content');

    -- Поиск
    CALL str_search_in_storage('%SQL%');

    CALL storage_read('hello.txt', v_content);
    CALL counter_increment('ops_total');
END$$

-- Демонстрация фигур
CREATE PROCEDURE main_demo_shapes()
BEGIN
    DECLARE v_circle_id  INT;
    DECLARE v_rect_id    INT;
    DECLARE v_area       DECIMAL(18,6);
    DECLARE v_is_square  TINYINT(1);

    CALL shape_create_circle(5.0, 'red',  v_circle_id);
    CALL shape_create_rect(4.0, 4.0, 'blue', v_rect_id);

    SET v_area      = shape_area(v_circle_id);
    SET v_is_square = shape_is_square(v_rect_id);

    IF v_is_square THEN
        CALL counter_increment('ops_total');
    END IF;
END$$

-- Демонстрация животных
CREATE PROCEDURE main_demo_animals()
BEGIN
    DECLARE v_dog_id  INT;
    DECLARE v_phrase  VARCHAR(200);

    CALL animal_create('dog', 'Buddy', NULL, v_dog_id);
    CALL dog_learn_trick(v_dog_id, 'sit');
    CALL dog_learn_trick(v_dog_id, 'shake');

    SET v_phrase = animal_speak(v_dog_id);
    CALL dog_show_tricks(v_dog_id);
    CALL counter_increment('ops_total');
END$$

-- Демонстрация утилит
CREATE PROCEDURE main_demo_utils()
BEGIN
    DECLARE v_fact   BIGINT;
    DECLARE v_gcd    BIGINT;
    DECLARE v_sum    BIGINT;
    DECLARE v_is_p   TINYINT(1);

    SET v_fact = util_factorial(10);        -- 3628800
    SET v_gcd  = util_gcd(48, 18);          -- 6
    SET v_is_p = util_is_prime(97);         -- 1
    CALL util_sum_array('1,2,3,4,5', v_sum); -- 15
    CALL counter_increment('ops_total');
END$$

-- Демонстрация строк
CREATE PROCEDURE main_demo_strings()
BEGIN
    DECLARE v_norm    VARCHAR(1000);
    DECLARE v_is_pal  TINYINT(1);
    DECLARE v_count   INT;
    DECLARE v_wrapped VARCHAR(1200);

    SET v_norm   = str_normalize('  hello World  '); -- 'HELLO WORLD'
    SET v_is_pal = str_is_palindrome('racecar');     -- 1
    SET v_count  = str_count_occurrences('abcabc', 'abc'); -- 2
    SET v_wrapped = str_wrap('content', '[', ']');   -- '[content]'
    CALL counter_increment('ops_total');
END$$

-- Главный запуск: полный цикл демонстрации
CREATE PROCEDURE main_run()
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        CALL counter_increment('errors_total');
        RESIGNAL;
    END;

    CALL main_init();
    CALL main_demo_calculator();
    CALL main_demo_storage();
    CALL main_demo_shapes();
    CALL main_demo_animals();
    CALL main_demo_utils();
    CALL main_demo_strings();

    -- Итоговая статистика
    SELECT
        counter_get('ops_total')    AS ops_done,
        counter_get('files_total')  AS files_stored,
        counter_get('errors_total') AS errors;
END$$

-- Представление итоговой статистики
CREATE VIEW main_summary AS
    SELECT
        (SELECT value FROM counters WHERE name = 'ops_total')    AS ops_total,
        (SELECT value FROM counters WHERE name = 'files_total')  AS files_total,
        (SELECT value FROM counters WHERE name = 'errors_total') AS errors_total$$

DELIMITER ;
