-- classes.sql
-- Хранимые процедуры моделирования иерархии объектов: фигуры и животные.
-- Аналог classes из других малых тест-проектов.

DELIMITER $$

-- Таблица фигур
CREATE TABLE IF NOT EXISTS shapes (
    id        INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
    shape_type VARCHAR(20)  NOT NULL,           -- 'circle', 'rectangle'
    color     VARCHAR(50)   NOT NULL DEFAULT 'white',
    param1    DECIMAL(10,4) NOT NULL DEFAULT 0, -- radius / width
    param2    DECIMAL(10,4) NOT NULL DEFAULT 0  -- height (для прямоугольника)
) ENGINE=InnoDB$$

-- Таблица животных
CREATE TABLE IF NOT EXISTS animals (
    id        INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    kind      VARCHAR(20)  NOT NULL,            -- 'dog', 'generic'
    name      VARCHAR(100) NOT NULL,
    sound     VARCHAR(50)  NOT NULL DEFAULT 'unknown'
) ENGINE=InnoDB$$

-- Таблица трюков (только для собак)
CREATE TABLE IF NOT EXISTS dog_tricks (
    dog_id    INT          NOT NULL,
    trick     VARCHAR(100) NOT NULL,
    PRIMARY KEY (dog_id, trick)
) ENGINE=InnoDB$$

-- ── Фигуры ───────────────────────────────────────────────────────────────────

-- Создать круг
CREATE PROCEDURE shape_create_circle(IN p_radius DECIMAL(10,4),
                                     IN p_color  VARCHAR(50),
                                     OUT p_id    INT)
BEGIN
    INSERT INTO shapes(shape_type, color, param1) VALUES ('circle', p_color, p_radius);
    SET p_id = LAST_INSERT_ID();
END$$

-- Создать прямоугольник
CREATE PROCEDURE shape_create_rect(IN p_width  DECIMAL(10,4),
                                   IN p_height DECIMAL(10,4),
                                   IN p_color  VARCHAR(50),
                                   OUT p_id    INT)
BEGIN
    INSERT INTO shapes(shape_type, color, param1, param2)
        VALUES ('rectangle', p_color, p_width, p_height);
    SET p_id = LAST_INSERT_ID();
END$$

-- Площадь фигуры
CREATE FUNCTION shape_area(p_id INT) RETURNS DECIMAL(18,6)
    READS SQL DATA
BEGIN
    DECLARE v_type  VARCHAR(20);
    DECLARE v_p1    DECIMAL(10,4);
    DECLARE v_p2    DECIMAL(10,4);
    DECLARE v_area  DECIMAL(18,6) DEFAULT 0;

    SELECT shape_type, param1, param2 INTO v_type, v_p1, v_p2
        FROM shapes WHERE id = p_id;

    IF v_type IS NULL THEN
        RETURN 0;
    END IF;

    CASE v_type
        WHEN 'circle'    THEN SET v_area = 3.14159265 * v_p1 * v_p1;
        WHEN 'rectangle' THEN SET v_area = v_p1 * v_p2;
        ELSE SET v_area = 0;
    END CASE;

    RETURN v_area;
END$$

-- Периметр фигуры
CREATE FUNCTION shape_perimeter(p_id INT) RETURNS DECIMAL(18,6)
    READS SQL DATA
BEGIN
    DECLARE v_type VARCHAR(20);
    DECLARE v_p1   DECIMAL(10,4);
    DECLARE v_p2   DECIMAL(10,4);
    DECLARE v_peri DECIMAL(18,6) DEFAULT 0;

    SELECT shape_type, param1, param2 INTO v_type, v_p1, v_p2
        FROM shapes WHERE id = p_id;

    CASE v_type
        WHEN 'circle'    THEN SET v_peri = 2 * 3.14159265 * v_p1;
        WHEN 'rectangle' THEN SET v_peri = 2 * (v_p1 + v_p2);
        ELSE SET v_peri = 0;
    END CASE;

    RETURN v_peri;
END$$

-- Является ли прямоугольник квадратом
CREATE FUNCTION shape_is_square(p_id INT) RETURNS TINYINT(1)
    READS SQL DATA
BEGIN
    DECLARE v_type VARCHAR(20);
    DECLARE v_p1   DECIMAL(10,4);
    DECLARE v_p2   DECIMAL(10,4);

    SELECT shape_type, param1, param2 INTO v_type, v_p1, v_p2
        FROM shapes WHERE id = p_id;

    IF v_type <> 'rectangle' THEN
        RETURN 0;
    END IF;

    RETURN IF(v_p1 = v_p2, 1, 0);
END$$

-- Представление всех фигур с площадью
CREATE VIEW shapes_with_area AS
    SELECT id, shape_type, color,
           param1, param2
    FROM shapes$$

-- ── Животные ─────────────────────────────────────────────────────────────────

-- Создать животное
CREATE PROCEDURE animal_create(IN p_kind  VARCHAR(20),
                               IN p_name  VARCHAR(100),
                               IN p_sound VARCHAR(50),
                               OUT p_id   INT)
BEGIN
    IF p_sound IS NULL OR p_sound = '' THEN
        CASE p_kind
            WHEN 'dog' THEN SET p_sound = 'Woof';
            ELSE            SET p_sound = 'unknown';
        END CASE;
    END IF;
    INSERT INTO animals(kind, name, sound) VALUES (p_kind, p_name, p_sound);
    SET p_id = LAST_INSERT_ID();
END$$

-- Животное «говорит»
CREATE FUNCTION animal_speak(p_id INT) RETURNS VARCHAR(200)
    READS SQL DATA
BEGIN
    DECLARE v_name  VARCHAR(100);
    DECLARE v_sound VARCHAR(50);

    SELECT name, sound INTO v_name, v_sound FROM animals WHERE id = p_id;

    IF v_name IS NULL THEN
        RETURN 'unknown animal';
    END IF;

    RETURN CONCAT(v_name, ' says ', v_sound);
END$$

-- Выучить трюк (только для собак)
CREATE PROCEDURE dog_learn_trick(IN p_dog_id INT, IN p_trick VARCHAR(100))
BEGIN
    DECLARE v_kind VARCHAR(20);

    SELECT kind INTO v_kind FROM animals WHERE id = p_dog_id;

    IF v_kind IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Animal not found';
    END IF;

    IF v_kind <> 'dog' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only dogs can learn tricks';
    END IF;

    INSERT IGNORE INTO dog_tricks(dog_id, trick) VALUES (p_dog_id, p_trick);
END$$

-- Показать трюки собаки
CREATE PROCEDURE dog_show_tricks(IN p_dog_id INT)
BEGIN
    DECLARE v_name  VARCHAR(100);
    DECLARE v_count INT DEFAULT 0;

    SELECT name INTO v_name FROM animals WHERE id = p_dog_id;
    SELECT COUNT(*) INTO v_count FROM dog_tricks WHERE dog_id = p_dog_id;

    IF v_count = 0 THEN
        SELECT CONCAT(v_name, ' knows no tricks') AS result;
    ELSE
        SELECT GROUP_CONCAT(trick ORDER BY trick SEPARATOR ', ') AS tricks
        FROM dog_tricks WHERE dog_id = p_dog_id;
    END IF;
END$$

DELIMITER ;
