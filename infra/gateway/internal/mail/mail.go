// Package mail sends transactional email (verification, password reset).
package mail

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"time"
)

type Mailer interface {
	Send(to, subject, text string) error
}

// HTMLMailer is a Mailer that can also send a styled HTML body alongside the plain-text one.
type HTMLMailer interface {
	Mailer
	SendHTML(to, subject, text, html string) error
}

// Resend sends through the Resend HTTP API (https://resend.com/docs/api-reference/emails/send-email).
type Resend struct {
	APIKey   string
	From     string // e.g. "Asirive <no-reply@asirive.com>" on your verified domain
	Endpoint string // default https://api.resend.com/emails
	Client   *http.Client
}

func (m *Resend) Send(to, subject, text string) error { return m.send(to, subject, text, "") }

// SendHTML sends both parts (multipart/alternative); clients that cannot show HTML fall back to text.
func (m *Resend) SendHTML(to, subject, text, html string) error {
	return m.send(to, subject, text, html)
}

func (m *Resend) send(to, subject, text, html string) error {
	ep := m.Endpoint
	if ep == "" {
		ep = "https://api.resend.com/emails"
	}
	c := m.Client
	if c == nil {
		c = &http.Client{Timeout: 10 * time.Second}
	}
	msg := map[string]any{"from": m.From, "to": []string{to}, "subject": subject, "text": text}
	if html != "" {
		msg["html"] = html
	}
	body, _ := json.Marshal(msg)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "POST", ep, bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+m.APIKey)
	req.Header.Set("Content-Type", "application/json")
	res, err := c.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode/100 != 2 {
		b, _ := io.ReadAll(io.LimitReader(res.Body, 512))
		return fmt.Errorf("resend: %s: %s", res.Status, b)
	}
	return nil
}

// Log prints mail to the gateway log. DEV ONLY: it exposes tokens in logs.
type Log struct{}

func (Log) Send(to, subject, text string) error {
	log.Printf("DEV MAIL to=%s subject=%q\n%s", to, subject, text)
	return nil
}
