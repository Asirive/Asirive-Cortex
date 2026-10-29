// Package web embeds the fleet dashboard served by the gateway.
package web

import "embed"

//go:embed index.html
var FS embed.FS
