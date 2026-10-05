-- Campus Event Management Platform - MySQL schema
-- Run once:  mysql -u root -p < schema.sql

CREATE DATABASE IF NOT EXISTS campus_events
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE campus_events;

DROP TABLE IF EXISTS certificates;
DROP TABLE IF EXISTS feedback;
DROP TABLE IF EXISTS attendance;
DROP TABLE IF EXISTS registrations;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

-- Students, organizers and administrators share one table and are separated
-- by role, so that login and access control are handled in one place.
CREATE TABLE users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  name          VARCHAR(120)  NOT NULL,
  email         VARCHAR(160)  NOT NULL UNIQUE,
  password_hash VARCHAR(255)  NOT NULL,
  role          ENUM('student','organizer','admin') NOT NULL DEFAULT 'student',
  usn           VARCHAR(20)   DEFAULT NULL UNIQUE,
  department    VARCHAR(80)   DEFAULT NULL,
  phone         VARCHAR(20)   DEFAULT NULL,
  is_active     TINYINT(1)    NOT NULL DEFAULT 1,
  created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login    DATETIME      DEFAULT NULL,
  INDEX idx_users_role (role)
) ENGINE=InnoDB;

CREATE TABLE events (
  id                    INT AUTO_INCREMENT PRIMARY KEY,
  title                 VARCHAR(160) NOT NULL,
  description           TEXT,
  category              VARCHAR(60)  NOT NULL DEFAULT 'General',
  venue                 VARCHAR(160) NOT NULL,
  start_datetime        DATETIME     NOT NULL,
  end_datetime          DATETIME     NOT NULL,
  registration_deadline DATETIME     NOT NULL,
  capacity              INT          NOT NULL DEFAULT 100,
  -- Wi-Fi attendance settings
  wifi_ssid             VARCHAR(64)  DEFAULT NULL,
  wifi_cidr             VARCHAR(255) DEFAULT NULL,   -- e.g. '10.10.4.0/22,192.168.20.0/24'
  wifi_public_ip        VARCHAR(45)  DEFAULT NULL,   -- campus NAT gateway, weaker fallback
  -- Workflow
  status                ENUM('pending','approved','rejected','cancelled')
                        NOT NULL DEFAULT 'pending',
  review_note           VARCHAR(255) DEFAULT NULL,
  organizer_id          INT          NOT NULL,
  created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_events_organizer FOREIGN KEY (organizer_id)
    REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_events_status_start (status, start_datetime)
) ENGINE=InnoDB;

CREATE TABLE registrations (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  event_id      INT NOT NULL,
  student_id    INT NOT NULL,
  status        ENUM('registered','cancelled') NOT NULL DEFAULT 'registered',
  registered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_reg_event   FOREIGN KEY (event_id)   REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_reg_student FOREIGN KEY (student_id) REFERENCES users(id)  ON DELETE CASCADE,
  -- one row per student per event: blocks duplicate registrations
  UNIQUE KEY uq_registration (event_id, student_id)
) ENGINE=InnoDB;

CREATE TABLE attendance (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  event_id      INT NOT NULL,
  student_id    INT NOT NULL,
  marked_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ip_address    VARCHAR(45)  NOT NULL,
  method        ENUM('wifi_subnet','campus_gateway','manual') NOT NULL,
  ssid_reported VARCHAR(64) DEFAULT NULL,
  marked_by     INT DEFAULT NULL,              -- set when an organizer marks it manually
  CONSTRAINT fk_att_event   FOREIGN KEY (event_id)   REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_att_student FOREIGN KEY (student_id) REFERENCES users(id)  ON DELETE CASCADE,
  -- one row per student per event: blocks duplicate attendance
  UNIQUE KEY uq_attendance (event_id, student_id)
) ENGINE=InnoDB;

CREATE TABLE feedback (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  event_id     INT NOT NULL,
  student_id   INT NOT NULL,
  rating       TINYINT NOT NULL,
  comments     TEXT,
  submitted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_fb_event   FOREIGN KEY (event_id)   REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_fb_student FOREIGN KEY (student_id) REFERENCES users(id)  ON DELETE CASCADE,
  CONSTRAINT chk_rating CHECK (rating BETWEEN 1 AND 5),
  UNIQUE KEY uq_feedback (event_id, student_id)
) ENGINE=InnoDB;

CREATE TABLE certificates (
  id               INT AUTO_INCREMENT PRIMARY KEY,
  event_id         INT NOT NULL,
  student_id       INT NOT NULL,
  certificate_code VARCHAR(40) NOT NULL UNIQUE,
  issued_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cert_event   FOREIGN KEY (event_id)   REFERENCES events(id) ON DELETE CASCADE,
  CONSTRAINT fk_cert_student FOREIGN KEY (student_id) REFERENCES users(id)  ON DELETE CASCADE,
  UNIQUE KEY uq_certificate (event_id, student_id)
) ENGINE=InnoDB;