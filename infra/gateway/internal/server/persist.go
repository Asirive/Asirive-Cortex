package server

import (
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
}

// SaveState writes registrations, releases and the audit log to path atomically
// (temp file, fsync, rename) with owner-only permissions: it holds credential hashes.
func (s *Server) SaveState(path string) error {
	st := state{Version: 1, SavedAt: time.Now(), Devices: s.Reg.Snapshot()}
	if s.OTA != nil {
		b, err := s.OTA.Snapshot()
		if err != nil {
			return err
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
	data, err := json.Marshal(st)
	if err != nil {
		return err
	}
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

// LoadState restores a previous SaveState. A missing file is a clean first start.
func (s *Server) LoadState(path string) error {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		return err
	}
	var st state
	if err := json.Unmarshal(data, &st); err != nil {
		return err
	}
	if st.Version != 1 {
		return errors.New("unknown state file version")
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
