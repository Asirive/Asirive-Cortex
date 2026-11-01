package server

import (
	"context"
	"database/sql"
	"errors"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib"
)

// PGStore keeps the state document in Postgres and uses a session-level advisory
// lock so only one gateway writes at a time (the others are warm standbys that take
// over when the leader's connection drops). This is failover, not active-active.
type PGStore struct {
	db   *sql.DB
	conn *sql.Conn // holds the advisory lock for its lifetime
}

const lockID = 7263905124 // arbitrary app-wide constant

func OpenPG(ctx context.Context, dsn string) (*PGStore, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(3)
	if err := db.PingContext(ctx); err != nil {
		return nil, err
	}
	if _, err := db.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS cortex_state (
		id int PRIMARY KEY CHECK (id = 1), doc bytea NOT NULL, updated_at timestamptz NOT NULL DEFAULT now())`); err != nil {
		return nil, err
	}
	return &PGStore{db: db}, nil
}

// TryLead attempts to become the writer; false means another gateway holds the lock.
func (p *PGStore) TryLead(ctx context.Context) (bool, error) {
	if p.conn != nil {
		return true, nil
	}
	c, err := p.db.Conn(ctx)
	if err != nil {
		return false, err
	}
	var ok bool
	if err := c.QueryRowContext(ctx, `SELECT pg_try_advisory_lock($1)`, lockID).Scan(&ok); err != nil || !ok {
		c.Close()
		return false, err
	}
	p.conn = c
	return true, nil
}

// StillLeader checks the lock connection is alive; if not, the lock is gone and writing must stop.
func (p *PGStore) StillLeader(ctx context.Context) bool {
	if p.conn == nil {
		return false
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	var n int
	return p.conn.QueryRowContext(ctx, `SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted`).Scan(&n) == nil && n > 0
}

func (p *PGStore) Read() ([]byte, error) {
	var b []byte
	err := p.db.QueryRow(`SELECT doc FROM cortex_state WHERE id = 1`).Scan(&b)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return b, err
}

func (p *PGStore) Write(b []byte) error {
	if p.conn == nil {
		return errors.New("not the leader: refusing to write state")
	}
	_, err := p.db.Exec(`INSERT INTO cortex_state (id, doc) VALUES (1, $1)
		ON CONFLICT (id) DO UPDATE SET doc = EXCLUDED.doc, updated_at = now()`, b)
	return err
}
