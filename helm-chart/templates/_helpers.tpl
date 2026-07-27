{{/*
Release-scoped resource name prefix, e.g. "myrelease-dtlab". Lets multiple
releases of this chart coexist in the same namespace without colliding.
*/}}
{{- define "dtlab.fullname" -}}
{{- if contains .Chart.Name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Standard labels applied to every resource.
*/}}
{{- define "dtlab.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for a given component (e.g. "backend", "frontend", "postgres").
Must stay stable across releases since Deployment selectors are immutable.
*/}}
{{- define "dtlab.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}
