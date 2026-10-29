package server

import (
	"crypto/ed25519"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"time"

	"github.com/asirive/cortex/gateway/internal/registry"
)

type state struct {
	Version   int               `json:"version"`
	SavedAt   time.Time         `json:"saved_at"`
	Devices   []registry.Record `json:"devices"`
	Releases  json.RawMessage   `json:"releases,omitempty"`
	Audit     []AuditLine       `json:"audit"`
	Operators []*Operator       `json:"operators,omitempty"`
	Accounts  json.RawMessage   `json:"accounts,omitempty"`
	Social    json.RawMessage   `json:"social,omitempty"`
	CmdKey    []byte            `json:"command_key,omitempty"`
}

// StateStore is where the state document lives: a file (single node) or Postgres.
type StateStore interface {
	Read() ([]byte, error) // (nil, nil) when nothing has been saved yet
	Write([]byte) error
}

// SaveState / LoadState use a file store.
func (s *Server) SaveState(path string) error { return s.SaveTo(FileStore{path}) }
func (s *Server) LoadState(path string) error { return s.LoadFrom(FileStore{path}) }

func (s *Server) SaveTo(st StateStore) error {
	data, err := s.marshalState()
	if err != nil {
		return err
	}
	return st.Write(data)
}

func (s *Server) marshalState() ([]byte, error) {
	st := state{Version: 1, SavedAt: time.Now(), Devices: s.Reg.Snapshot(), CmdKey: s.CmdKey}
	if s.OTA != nil {
		b, err := s.OTA.Snapshot()
		if err != nil {
			return nil, err
		}
		st.Releases = b
	}
	if b, err := s.Accounts.Snapshot(); err == nil {
		st.Accounts = b
	}
	if b, err := s.Social.Snapshot(); err == nil {
		st.Social = b
	}
	s.mu.Lock()
	st.Audit = append([]AuditLine(nil), s.audit...)
	for _, o := range s.operators {
		c := *o
		st.Operators = append(st.Operators, &c)
	}
	s.mu.Unlock()
	return json.Marshal(st)
}

// FileStore writes atomically (temp file, fsync, rename) with owner-only permissions: it holds credential hashes.
type FileStore struct{ Path string }

func (f FileStore) Read() ([]byte, error) {
	b, err := os.ReadFile(f.Path)
	if errors.Is(err, os.ErrNotExist) {
		return nil, nil
	}
	return b, err
}

func (f FileStore) Write(data []byte) error {
	path := f.Path
	tmp, err := os.CreateTemp(filepath.Dir(path), ".state-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(0o600); err != nil {
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		return err
	}
	if err := tmp.Sync(); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), path)
}

// LoadFrom restores a previous save. Nothing saved yet is a clean first start.
func (s *Server) LoadFrom(store StateStore) error {
	data, err := store.Read()
	if err != nil {
		return err
	}
	if data == nil {
		return nil
	}
	var st state
	if err := json.Unmarshal(data, &st); err != nil {
		return err
	}
	if st.Version != 1 {
		return errors.New("unknown state file version")
	}
	if len(st.CmdKey) == ed25519.PrivateKeySize {
		s.CmdKey = ed25519.PrivateKey(st.CmdKey)
	}
	s.Reg.Restore(st.Devices)
	if len(st.Social) > 0 {
		if err := s.Social.Restore(st.Social); err != nil {
			return err
		}
	}
	if len(st.Accounts) > 0 {
		if err := s.Accounts.Restore(st.Accounts); err != nil {
			return err
		}
	}
	if s.OTA != nil && len(st.Releases) > 0 {
		if err := s.OTA.Restore(st.Releases); err != nil {
			return err
		}
	}
	s.mu.Lock()
	s.audit = st.Audit
	s.operators = map[string]*Operator{}
	for _, o := range st.Operators {
		s.operators[o.Name] = o
	}
	s.mu.Unlock()
	return nil
}
