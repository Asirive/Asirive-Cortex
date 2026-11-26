package server

import (
	"embed"
	"html"
	"log"
	"net/http"
	"net/url"
	"strings"
)

// Asirive Cortex brand: the same tokens as the app (apps/mobile/lib/theme.dart). Near-black ground, green-black
// surfaces, off-white text, #EAFF00 as the only accent. Display type is Anton in caps, body is Space Grotesk,
// labels are JetBrains Mono in caps with wide tracking.
const (
	brandGround  = "#0a0a08"
	brandSurface = "#131a14"
	brandLine    = "#223024"
	brandOutline = "#5c6f5f"
	brandText    = "#f4f4ec"
	brandMuted   = "#b6bfb0"
	brandFaint   = "#9aa394"
	brandAccent  = "#eaff00"
	brandDanger  = "#ff8a7d"

	fontDisplay = `'Anton',Impact,'Arial Narrow Bold','Helvetica Neue Condensed',sans-serif`
	fontBody    = `'Space Grotesk','Segoe UI',Helvetica,Arial,sans-serif`
	fontMono    = `'JetBrains Mono',Consolas,Menlo,'Courier New',monospace`
)

// The app's own font files, served at /v1/brand/ so the emails and the link pages use the real typefaces.
// (/v1/* is the only public path outside the console's login.)
//
//go:embed brand/*.ttf
var brandFS embed.FS

type mailKind struct {
	subject, mono, heading, lead, button, note string
}

var mailKinds = map[string]mailKind{
	"verify": {
		subject: "Confirm your Asirive account",
		mono:    "Account · Confirm email",
		heading: "Confirm your email",
		lead:    "Thanks for signing up. Confirm your email address, then open the Asirive app and sign in.",
		button:  "Confirm email",
		note:    "If you didn't sign up for Asirive, you can ignore this email.",
	},
	"reset": {
		subject: "Reset your Asirive password",
		mono:    "Account · New password",
		heading: "Choose a new password",
		lead:    "We got a request to reset your Asirive password. This link works for 1 hour.",
		button:  "Choose a new password",
		note:    "If you didn't ask for this, you can ignore this email. Your password stays the same.",
	},
}

// webLink is the https page a mail client can open. Falls back to the asirive:// deep link when no public
// origin is configured (dev).
func (s *Server) webLink(kind, tok string) string {
	if s.WebBase == "" {
		return s.link(kind, tok)
	}
	return s.WebBase + "/v1/link/" + kind + "?token=" + url.QueryEscape(tok)
}

// accountMail sends the verification / reset email: plain text plus an HTML part in the Asirive theme.
// It never blocks or fails the request (a mail outage must not reveal which emails exist).
func (s *Server) accountMail(to, kind, tok string) {
	k, ok := mailKinds[kind]
	if !ok {
		return
	}
	link := s.webLink(kind, tok)
	text := k.heading + "\n\n" + k.lead + "\n\n" + k.button + ":\n" + link + "\n\n" + k.note + "\n\nAsirive Cortex"
	htm := renderMailHTML(k, link, s.WebBase)
	go func() {
		var err error
		if hm, ok := s.Mailer.(interface {
			SendHTML(to, subject, text, html string) error
		}); ok {
			err = hm.SendHTML(to, k.subject, text, htm)
		} else {
			err = s.Mailer.Send(to, k.subject, text)
		}
		if err != nil {
			log.Printf("mail to account failed: %v", err)
		}
	}()
}

// logoCells is the Asirive mark on a 10x10 grid (same shapes as CxLogo in the app): true = black.
func logoCells(r, c int) bool {
	in := func(c0, c1, r0, r1 int) bool { return c >= c0 && c <= c1 && r >= r0 && r <= r1 }
	return in(2, 3, 2, 5) || in(2, 3, 7, 7) || in(6, 7, 4, 7) || in(6, 7, 2, 2) || in(4, 5, 4, 5)
}

// accentBg paints a cell yellow in a way dark-mode mail apps leave alone: Outlook rewrites background-color
// but not background-image, and the [data-ogsb] rule in the head puts the colour back where it does rewrite.
func accentBg() string {
	return `background-color:` + brandAccent + `;background-image:linear-gradient(` + brandAccent + `,` + brandAccent + `);`
}

// mailLogo draws the mark as a table, so it shows even when the mail app blocks images.
func mailLogo(cell int) string {
	var b strings.Builder
	px := func(n int) string { return itoa(n) }
	b.WriteString(`<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="` + px(cell*10) + `" style="border-collapse:collapse;width:` + px(cell*10) + `px;">`)
	for r := 0; r < 10; r++ {
		b.WriteString("<tr>")
		for c := 0; c < 10; {
			black := logoCells(r, c)
			run := 1
			for c+run < 10 && logoCells(r, c+run) == black {
				run++
			}
			w := run * cell
			st := `width:` + px(w) + `px;height:` + px(cell) + `px;font-size:0;line-height:0;mso-line-height-rule:exactly;`
			if black {
				b.WriteString(`<td class="cx-ink-bg" width="` + px(w) + `" height="` + px(cell) + `" bgcolor="` + brandGround + `" style="` + st + `background-color:` + brandGround + `;">&#8203;</td>`)
			} else {
				b.WriteString(`<td class="cx-acc" width="` + px(w) + `" height="` + px(cell) + `" bgcolor="` + brandAccent + `" style="` + st + accentBg() + `">&#8203;</td>`)
			}
			c += run
		}
		b.WriteString("</tr>")
	}
	b.WriteString("</table>")
	return b.String()
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	var d []byte
	for n > 0 {
		d = append([]byte{byte('0' + n%10)}, d...)
		n /= 10
	}
	return string(d)
}

// fontFaces points @font-face at the gateway's copy of the app fonts. Mail apps that load web fonts (Apple Mail,
// iOS, Outlook for Mac, Samsung) show the real type; the rest fall back to Impact / Segoe UI / Consolas.
func fontFaces(base string) string {
	if base == "" {
		return ""
	}
	f := func(fam, file string) string {
		return `@font-face{font-family:'` + fam + `';src:url('` + base + `/v1/brand/` + file + `') format('truetype');font-display:swap;}`
	}
	return f("Anton", "Anton-Regular.ttf") + f("Space Grotesk", "SpaceGrotesk.ttf") + f("JetBrains Mono", "JetBrainsMono.ttf")
}

// renderMailHTML is table-based with inline styles: that is what Gmail and Outlook render reliably.
func renderMailHTML(k mailKind, link, base string) string {
	l := html.EscapeString(link)
	e := html.EscapeString
	label := `font-family:` + fontMono + `;font-size:12px;line-height:16px;letter-spacing:2px;text-transform:uppercase;color:` + brandFaint + `;`
	var b strings.Builder
	b.WriteString(`<!doctype html><html lang="en" xmlns="http://www.w3.org/1999/xhtml"><head><meta charset="utf-8">` +
		`<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="x-apple-disable-message-reformatting">` +
		`<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">` +
		`<title>` + e(k.subject) + `</title><style>` + fontFaces(base) +
		`:root{color-scheme:light dark;supported-color-schemes:light dark}` +
		`body{margin:0;padding:0;background:` + brandGround + `}a{text-decoration:none}` +
		// Outlook.com / new Outlook dark mode: it marks every colour it changed with data-ogsc / data-ogsb. Put ours back.
		`[data-ogsb] .cx-acc{background-color:` + brandAccent + ` !important}` +
		`[data-ogsb] .cx-ink-bg{background-color:` + brandGround + ` !important}` +
		`[data-ogsb] .cx-ground{background-color:` + brandGround + ` !important}` +
		`[data-ogsb] .cx-surface{background-color:` + brandSurface + ` !important}` +
		`[data-ogsc] .cx-ink{color:` + brandGround + ` !important}` +
		`[data-ogsc] .cx-acc-t{color:` + brandAccent + ` !important}` +
		`[data-ogsc] .cx-text{color:` + brandText + ` !important}` +
		`@media (max-width:480px){.cx-h1{font-size:38px !important;line-height:40px !important}.cx-pad{padding-left:16px !important;padding-right:16px !important}}` +
		`</style></head>`)
	b.WriteString(`<body class="cx-ground" style="margin:0;padding:0;background-color:` + brandGround + `;">`)
	// preheader: the line inbox lists show under the subject
	b.WriteString(`<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">` + e(k.lead) + `</div>`)
	b.WriteString(`<table role="presentation" class="cx-ground" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="` + brandGround + `" style="background-color:` + brandGround + `;"><tr><td align="center" class="cx-pad" style="padding:36px 20px 40px 20px;">`)
	b.WriteString(`<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">`)

	// header: the mark + ASIRIVE CORTEX
	b.WriteString(`<tr><td style="padding:0 0 32px 0;"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>` +
		`<td valign="middle" style="width:40px;">` + mailLogo(4) + `</td>` +
		`<td valign="middle" style="padding-left:14px;">` +
		`<div class="cx-acc-t" style="font-family:` + fontDisplay + `;font-size:22px;line-height:22px;letter-spacing:1px;color:` + brandAccent + `;">ASIRIVE</div>` +
		`<div style="padding-top:5px;` + label + `font-size:11px;line-height:11px;">Cortex</div></td></tr></table></td></tr>`)

	// mono label, big yellow Anton title, lead
	b.WriteString(`<tr><td style="padding:0 0 14px 0;` + label + `">` + e(k.mono) + `</td></tr>`)
	b.WriteString(`<tr><td class="cx-h1 cx-acc-t" style="padding:0 0 16px 0;font-family:` + fontDisplay + `;font-size:44px;line-height:46px;letter-spacing:1.3px;text-transform:uppercase;color:` + brandAccent + `;">` + e(strings.ToUpper(k.heading)) + `</td></tr>`)
	b.WriteString(`<tr><td class="cx-text" style="padding:0 0 28px 0;font-family:` + fontBody + `;font-size:16px;line-height:24px;color:` + brandMuted + `;">` + e(k.lead) + `</td></tr>`)

	// the pill button (same as CxButton: 56px high, fully round, yellow, near-black bold label)
	b.WriteString(`<tr><td style="padding:0 0 28px 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>` +
		`<td align="center" class="cx-acc" bgcolor="` + brandAccent + `" style="` + accentBg() + `border-radius:28px;">` +
		`<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" href="` + l + `" style="height:56px;v-text-anchor:middle;width:480px;" arcsize="50%" stroke="f" fillcolor="` + brandAccent + `"><center style="color:` + brandGround + `;font-family:Segoe UI,Arial,sans-serif;font-size:17px;font-weight:bold;">` + e(k.button) + `</center></v:roundrect><![endif]-->` +
		`<!--[if !mso]><!--><a href="` + l + `" class="cx-ink" style="display:block;padding:18px 24px;font-family:` + fontBody + `;font-size:17px;line-height:20px;font-weight:700;color:` + brandGround + `;text-decoration:none;border-radius:28px;">` + e(k.button) + `</a><!--<![endif]-->` +
		`</td></tr></table></td></tr>`)

	// fallback link in a surface tile (radius 22, like CxTile)
	b.WriteString(`<tr><td class="cx-surface" bgcolor="` + brandSurface + `" style="background-color:` + brandSurface + `;border-radius:22px;padding:16px 18px;">` +
		`<div style="` + label + `padding-bottom:8px;">Button not working? Open this link</div>` +
		`<a href="` + l + `" class="cx-acc-t" style="font-family:` + fontMono + `;font-size:12px;line-height:18px;color:` + brandAccent + `;word-break:break-all;text-decoration:underline;">` + l + `</a>` +
		`</td></tr>`)

	b.WriteString(`<tr><td style="padding:20px 4px 0 4px;font-family:` + fontBody + `;font-size:13px;line-height:19px;color:` + brandFaint + `;">` + e(k.note) + `</td></tr>`)
	b.WriteString(`<tr><td style="padding:28px 4px 0 4px;"><div style="height:1px;line-height:1px;font-size:0;background-color:` + brandLine + `;">&#8203;</div></td></tr>`)
	b.WriteString(`<tr><td style="padding:16px 4px 0 4px;` + label + `font-size:11px;">Asirive Cortex</td></tr>`)
	b.WriteString(`</table></td></tr></table></body></html>`)
	return b.String()
}

// brandFile serves the embedded app fonts. Mail apps fetch them cross-origin, so CORS is open (they are public).
func (s *Server) brandFile(w http.ResponseWriter, r *http.Request) {
	name := r.PathValue("file")
	if strings.ContainsAny(name, "/\\") || !strings.HasSuffix(name, ".ttf") {
		http.NotFound(w, r)
		return
	}
	b, err := brandFS.ReadFile("brand/" + name)
	if err != nil {
		http.NotFound(w, r)
		return
	}
	h := w.Header()
	h.Set("Content-Type", "font/ttf")
	h.Set("Cache-Control", "public, max-age=31536000, immutable")
	h.Set("Access-Control-Allow-Origin", "*")
	h.Set("X-Content-Type-Options", "nosniff")
	w.Write(b)
}

// The mark as SVG for the link pages (same grid as the email table and CxLogo).
const logoSVG = `<svg class="logo" viewBox="0 0 100 100" aria-hidden="true"><rect width="100" height="100" fill="` + brandAccent + `"/>` +
	`<g fill="#000"><rect x="20" y="20" width="20" height="40"/><rect x="20" y="70" width="20" height="10"/><rect x="60" y="40" width="20" height="40"/>` +
	`<rect x="60" y="20" width="20" height="10"/><rect x="40" y="40" width="20" height="20"/></g></svg>`

// linkPage is what the emailed https link opens. The token is read by the page's script, never templated into the
// HTML, and the page only acts when the person presses the button: mail scanners that pre-fetch links therefore
// cannot use up a single-use token.
func (s *Server) linkPage(w http.ResponseWriter, r *http.Request) {
	kind := r.PathValue("kind")
	k, ok := mailKinds[kind]
	if !ok {
		http.NotFound(w, r)
		return
	}
	h := w.Header()
	h.Set("Content-Type", "text/html; charset=utf-8")
	h.Set("Cache-Control", "no-store")
	h.Set("Referrer-Policy", "no-referrer")
	h.Set("X-Content-Type-Options", "nosniff")
	h.Set("X-Frame-Options", "DENY")
	h.Set("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
	field := ""
	if kind == "reset" {
		field = `<label for="pw">New password</label><div class="pw"><input id="pw" type="password" autocomplete="new-password" minlength="10" placeholder="At least 10 characters">` +
			`<button type="button" class="eye" id="eye" aria-label="Show password" aria-pressed="false">Show</button></div>` +
			`<label for="pw2">Type it again</label><input id="pw2" type="password" autocomplete="new-password" minlength="10">`
	}
	ff := func(fam, file string) string {
		return `@font-face{font-family:'` + fam + `';src:url('/v1/brand/` + file + `') format('truetype');font-display:swap}`
	}
	w.Write([]byte(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">` +
		`<meta name="robots" content="noindex"><meta name="theme-color" content="` + brandGround + `"><title>` + html.EscapeString(k.heading) + ` · Asirive</title><style>` +
		ff("Anton", "Anton-Regular.ttf") + ff("Space Grotesk", "SpaceGrotesk.ttf") + ff("JetBrains Mono", "JetBrainsMono.ttf") +
		`:root{color-scheme:dark;--g:` + brandGround + `;--s:` + brandSurface + `;--l:` + brandLine + `;--o:` + brandOutline + `;--t:` + brandText + `;--m:` + brandMuted + `;--f:` + brandFaint + `;--a:` + brandAccent + `;--d:` + brandDanger + `}` +
		`*{box-sizing:border-box}html,body{margin:0;background:var(--g);color:var(--t)}` +
		`body{font:16px/1.5 ` + fontBody + `;min-height:100vh;min-height:100dvh;display:flex;justify-content:center;padding:max(28px,env(safe-area-inset-top)) 16px max(24px,env(safe-area-inset-bottom))}` +
		`main{width:100%;max-width:440px;display:flex;flex-direction:column;gap:14px}` +
		`.top{display:flex;align-items:center;gap:12px;min-height:48px;margin-bottom:18px}.logo{width:44px;height:44px;display:block}` +
		`.word b{display:block;font:22px/1 ` + fontDisplay + `;letter-spacing:.04em;color:var(--a)}.word span{display:block;margin-top:5px;font:12px/1 ` + fontMono + `;letter-spacing:.14em;color:var(--f);text-transform:uppercase}` +
		`.mono{font:12px/1.3 ` + fontMono + `;letter-spacing:.14em;text-transform:uppercase;color:var(--f)}` +
		`h1{margin:0;font:clamp(38px,11vw,52px)/1 ` + fontDisplay + `;letter-spacing:.03em;text-transform:uppercase;color:var(--a)}` +
		`p{margin:0;color:var(--m)}` +
		`#form{display:flex;flex-direction:column;gap:8px;margin-top:10px}` +
		`label{padding-left:8px;font:12px/1.3 ` + fontMono + `;letter-spacing:.14em;text-transform:uppercase;color:var(--f)}` +
		`input{width:100%;height:52px;padding:0 20px;border-radius:26px;border:1.5px solid var(--l);background:var(--s);color:var(--t);font:500 16px ` + fontBody + `;outline:none;margin-bottom:8px;transition:border-color .2s}` +
		`input:focus{border:2px solid var(--a)}.pw{position:relative}.pw input{padding-right:84px}` +
		`.eye{position:absolute;right:6px;top:4px;height:44px;padding:0 16px;border:0;border-radius:22px;background:transparent;color:var(--t);font:600 14px ` + fontBody + `;cursor:pointer}` +
		`.btn{display:flex;align-items:center;justify-content:center;width:100%;height:56px;border:0;border-radius:28px;background:var(--a);color:var(--g);font:700 17px ` + fontBody + `;text-decoration:none;cursor:pointer;` +
		`transition:transform .12s cubic-bezier(.2,0,0,1),opacity .2s,background .2s;-webkit-tap-highlight-color:transparent}` +
		`.btn:active{transform:scale(.97)}.btn:disabled{background:var(--o);cursor:default}` +
		`.btn.out{background:transparent;color:var(--t);border:1.5px solid var(--o)}` +
		`:focus-visible{outline:2px solid var(--a);outline-offset:3px}` +
		`.msg{min-height:1.5em;color:var(--t)}.bad{color:var(--d)}.ok{color:var(--a)}.hide{display:none!important}` +
		`.spin{width:22px;height:22px;border-radius:50%;border:2.5px solid currentColor;border-right-color:transparent;animation:r .8s linear infinite}` +
		`.done{width:64px;height:64px;border-radius:50%;background:var(--a);display:flex;align-items:center;justify-content:center;margin-bottom:6px;animation:pop .5s cubic-bezier(.2,1.4,.4,1) both}` +
		`.done svg{width:30px;height:30px;stroke:var(--g);stroke-width:3.2;fill:none;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:40;stroke-dashoffset:40;animation:draw .45s .25s ease-out forwards}` +
		`.in>*{opacity:0;transform:translateY(14px);animation:up .5s cubic-bezier(.2,0,0,1) forwards}` +
		`.in>*:nth-child(2){animation-delay:.05s}.in>*:nth-child(3){animation-delay:.1s}.in>*:nth-child(4){animation-delay:.15s}.in>*:nth-child(5){animation-delay:.2s}.in>*:nth-child(n+6){animation-delay:.25s}` +
		`.foot{margin-top:auto;padding-top:28px}` +
		`@keyframes up{to{opacity:1;transform:none}}@keyframes r{to{transform:rotate(360deg)}}@keyframes pop{from{transform:scale(.4);opacity:0}}@keyframes draw{to{stroke-dashoffset:0}}` +
		`@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important;opacity:1!important;transform:none!important;stroke-dashoffset:0!important}}` +
		`</style></head><body><main class="in">` +
		`<div class="top">` + logoSVG + `<div class="word"><b>ASIRIVE</b><span>Cortex</span></div></div>` +
		`<div class="mono" id="mono">` + html.EscapeString(k.mono) + `</div>` +
		`<div id="tick" class="done hide" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></div>` +
		`<h1 id="h">` + html.EscapeString(k.heading) + `</h1><p id="lead">` + html.EscapeString(k.lead) + `</p>` +
		`<div id="form">` + field + `<button class="btn" id="go" type="button">` + html.EscapeString(k.button) + `</button></div>` +
		`<div class="msg" id="msg" role="status" aria-live="polite"></div>` +
		`<a class="btn hide" id="open" href="asirive://">Open the Asirive app</a>` +
		`<div class="mono foot">Asirive Cortex</div>` +
		`<script>(function(){var kind=` + jsString(kind) + `;var tok=new URLSearchParams(location.search).get("token")||"";` +
		`try{history.replaceState(null,"",location.pathname)}catch(e){}` +
		`var $=function(i){return document.getElementById(i)},go=$("go"),msg=$("msg"),label=go.textContent;` +
		`function say(t,c){msg.textContent=t;msg.className="msg "+(c||"")}` +
		`function busy(b){go.disabled=b;go.innerHTML=b?'<span class="spin" aria-hidden="true"></span>':"";if(!b)go.textContent=label;go.setAttribute("aria-busy",b?"true":"false")}` +
		`if($("eye"))$("eye").addEventListener("click",function(){var p=$("pw"),s=p.type==="password";p.type=s?"text":"password";$("pw2").type=p.type;this.textContent=s?"Hide":"Show";this.setAttribute("aria-pressed",s?"true":"false")});` +
		`if(!tok){go.disabled=true;say("This link is incomplete. Ask for a new email from the app.","bad")}` +
		`go.addEventListener("click",function(){var body={token:tok};if(kind==="reset"){var pw=$("pw").value;` +
		`if(pw.length<10){say("Use a password of at least 10 characters.","bad");$("pw").focus();return}` +
		`if(pw!==$("pw2").value){say("The two passwords don't match.","bad");$("pw2").focus();return}body.password=pw}` +
		`busy(true);say("");` +
		`fetch("/v1/auth/"+(kind==="reset"?"reset":"verify"),{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})` +
		`.then(function(r){return r.json().catch(function(){return{}}).then(function(j){return{ok:r.ok,j:j}})}).then(function(x){` +
		`if(x.ok){$("form").className="hide";$("lead").className="hide";$("tick").className="done";$("mono").textContent=kind==="reset"?"Account · Password changed":"Account · Confirmed";` +
		`$("h").textContent=kind==="reset"?"Password changed":"Email confirmed";say(kind==="reset"?"You can sign in with your new password.":"You can sign in to the Asirive app now.","ok");$("open").className="btn"}` +
		`else{busy(false);say((x.j&&x.j.error)||"Something went wrong. Try again.","bad")}` +
		`}).catch(function(){busy(false);say("Can't reach Asirive. Check your connection and try again.","bad")})});` +
		`})()</script></main></body></html>`))
}

// jsString returns s as a JS string literal. Only fixed kind names reach it, but keep it safe anyway.
func jsString(s string) string {
	out := `"`
	for _, c := range s {
		if (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') {
			out += string(c)
		}
	}
	return out + `"`
}
