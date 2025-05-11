-- Create table for category members
CREATE TABLE IF NOT EXISTS catmembers (
    date DATETIME NOT NULL,
    category TEXT NOT NULL,
    page TEXT NOT NULL,
    PRIMARY KEY (category, page)
);

-- Create table for category log
CREATE TABLE IF NOT EXISTS catlog (
    date DATETIME NOT NULL,
    category TEXT NOT NULL,
    page TEXT NOT NULL,
    added INTEGER NOT NULL,
    new INTEGER NOT NULL
);

-- Create table for statistics
CREATE TABLE IF NOT EXISTS stats (
    date DATETIME NOT NULL,
    articlecount INTEGER NOT NULL,
    opprydning INTEGER NOT NULL,
    oppdatering INTEGER NOT NULL,
    interwiki INTEGER NOT NULL,
    flytting INTEGER NOT NULL,
    fletting INTEGER NOT NULL,
    språkvask INTEGER NOT NULL,
    kilder INTEGER NOT NULL,
    ukategorisert INTEGER NOT NULL
);

-- Create table for clean log
CREATE TABLE IF NOT EXISTS cleanlog (
    date DATETIME NOT NULL,
    category TEXT NOT NULL,
    action TEXT NOT NULL,
    page TEXT NOT NULL,
    user TEXT NOT NULL,
    revision INTEGER NOT NULL
);