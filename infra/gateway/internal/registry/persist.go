package registry

// Record is the durable form of a Registration, including the secret hashes
// (never the plaintext claim code or token).
type Record struct {
	Registration
	ClaimHash []byte `json:"claim_hash,omitempty"`
	TokenHash []byte `json:"token_hash,omitempty"`
	PubKey    []byte `json:"pub_key,omitempty"`
}

// Snapshot returns every registration for persistence.
func (r *Registry) Snapshot() []Record {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]Record, 0, len(r.byID))
	for _, x := range r.byID {
		out = append(out, Record{Registration: *x, ClaimHash: x.claimHash[:], TokenHash: x.tokenHash[:], PubKey: x.pubKey})
	}
	return out
}

// Restore replaces the registry contents with a snapshot.
func (r *Registry) Restore(recs []Record) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.byID = map[string]*Registration{}
	for _, rec := range recs {
		x := rec.Registration
		copy(x.claimHash[:], rec.ClaimHash)
		copy(x.tokenHash[:], rec.TokenHash)
		x.pubKey = rec.PubKey
		r.byID[x.ID] = &x
	}
}
