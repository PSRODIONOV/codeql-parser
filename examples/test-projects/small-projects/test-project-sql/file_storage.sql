-- file_storage.sql
-- Хранимые процедуры управления хранилищем файловых записей в БД.
-- Аналог FileStorage из других малых тест-проектов.

DELIMITER $$

CREATE TABLE IF NOT EXISTS file_records (
    id          INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
    filename    VARCHAR(255)  NOT NULL,
    content     MEDIUMTEXT,
    size_bytes  INT           NOT NULL DEFAULT 0,
    created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    is_deleted  TINYINT(1)    NOT NULL DEFAULT 0,
    UNIQUE KEY uq_filename (filename)
) ENGINE=InnoDB$$

CREATE TABLE IF NOT EXISTS file_access_log (
    id          INT          NOT NULL AUTO_INCREMENT PRIMARY KEY,
    file_id     INT          NOT NULL,
    operation   VARCHAR(20)  NOT NULL,
    accessed_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB$$

-- Записать файл
CREATE PROCEDURE storage_write(IN p_filename VARCHAR(255), IN p_content MEDIUMTEXT)
BEGIN
    DECLARE v_size   INT DEFAULT 0;
    DECLARE v_id     INT DEFAULT 0;
    DECLARE v_exists INT DEFAULT 0;

    SET v_size = CHAR_LENGTH(p_content);

    SELECT COUNT(*) INTO v_exists
        FROM file_records WHERE filename = p_filename AND is_deleted = 0;

    IF v_exists > 0 THEN
        UPDATE file_records
            SET content = p_content, size_bytes = v_size
            WHERE filename = p_filename;
        SELECT id INTO v_id FROM file_records WHERE filename = p_filename;
    ELSE
        INSERT INTO file_records(filename, content, size_bytes)
            VALUES (p_filename, p_content, v_size);
        SET v_id = LAST_INSERT_ID();
    END IF;

    CALL storage_log_access(v_id, 'write');
END$$

-- Прочитать файл
CREATE PROCEDURE storage_read(IN p_filename VARCHAR(255), OUT p_content MEDIUMTEXT)
BEGIN
    DECLARE v_id      INT DEFAULT 0;
    DECLARE v_content MEDIUMTEXT;

    SELECT id, content INTO v_id, v_content
        FROM file_records
        WHERE filename = p_filename AND is_deleted = 0;

    IF v_id IS NULL OR v_id = 0 THEN
        SET p_content = NULL;
        RETURN;
    END IF;

    CALL storage_log_access(v_id, 'read');
    SET p_content = v_content;
END$$

-- Удалить файл (мягкое удаление)
CREATE PROCEDURE storage_delete(IN p_filename VARCHAR(255))
BEGIN
    DECLARE v_id INT DEFAULT 0;

    SELECT id INTO v_id
        FROM file_records WHERE filename = p_filename AND is_deleted = 0;

    IF v_id IS NULL OR v_id = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'File not found';
    END IF;

    UPDATE file_records SET is_deleted = 1 WHERE id = v_id;
    CALL storage_log_access(v_id, 'delete');
END$$

-- Проверить существование файла
CREATE FUNCTION storage_exists(p_filename VARCHAR(255)) RETURNS TINYINT(1)
    READS SQL DATA
BEGIN
    DECLARE v_cnt INT DEFAULT 0;
    SELECT COUNT(*) INTO v_cnt
        FROM file_records WHERE filename = p_filename AND is_deleted = 0;
    RETURN IF(v_cnt > 0, 1, 0);
END$$

-- Получить размер файла
CREATE FUNCTION storage_size(p_filename VARCHAR(255)) RETURNS INT
    READS SQL DATA
BEGIN
    DECLARE v_size INT DEFAULT -1;
    SELECT size_bytes INTO v_size
        FROM file_records WHERE filename = p_filename AND is_deleted = 0;
    RETURN IFNULL(v_size, -1);
END$$

-- Логировать обращение к файлу
CREATE PROCEDURE storage_log_access(IN p_file_id INT, IN p_op VARCHAR(20))
BEGIN
    INSERT INTO file_access_log(file_id, operation)
        VALUES (p_file_id, p_op);
END$$

-- Список файлов (представление)
CREATE VIEW storage_files AS
    SELECT id, filename, size_bytes, created_at, updated_at
    FROM file_records
    WHERE is_deleted = 0
    ORDER BY filename$$

-- Триггер: обновление счётчика при вставке записи
CREATE TRIGGER trg_file_after_insert
    AFTER INSERT ON file_records
    FOR EACH ROW
BEGIN
    CALL counter_increment('files_total');
END$$

-- Триггер: уменьшение счётчика при удалении
CREATE TRIGGER trg_file_after_delete
    AFTER UPDATE ON file_records
    FOR EACH ROW
BEGIN
    IF NEW.is_deleted = 1 AND OLD.is_deleted = 0 THEN
        CALL counter_decrement('files_total');
    END IF;
END$$

DELIMITER ;
