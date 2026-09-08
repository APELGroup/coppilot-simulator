{{/*
Release-scoped resource name prefix, e.g. "myrelease-simulator". Lets multiple
releases of this chart coexist in the same namespace without colliding.
*/}}
{{- define "simulator.fullname" -}}
{{- if contains .Chart.Name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Standard labels applied to every resource.
*/}}
{{- define "simulator.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels for a given component (e.g. "backend", "frontend", "postgres").
Must stay stable across releases since Deployment selectors are immutable.
*/}}
{{- define "simulator.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end }}

{{/*
Raw (unencoded) .dockerconfigjson built from imagePullSecret.{registry,username,password,email}.
Deliberately no b64enc here: this is rendered into a Secret's stringData so
Kubernetes encodes it server-side. Keeping the template output unencoded lets
tools like argocd-vault-plugin substitute <path:...> placeholders in the
values (for username/password) after Helm has rendered the manifest.
*/}}
{{- define "simulator.dockerconfigjson" -}}
{{- $entry := dict "username" .Values.imagePullSecret.username "password" .Values.imagePullSecret.password "email" .Values.imagePullSecret.email -}}
{{- dict "auths" (dict .Values.imagePullSecret.registry $entry) | toRawJson -}}
{{- end -}}

{{/*
Renders an imagePullSecrets: block for a pod spec, merging any pre-existing
secret names in .Values.imagePullSecrets with the chart-managed secret
(when .Values.imagePullSecret.create is true). Use with `nindent 6`.
*/}}
{{- define "simulator.imagePullSecrets" -}}
{{- $names := list -}}
{{- range .Values.imagePullSecrets -}}
{{- $names = append $names .name -}}
{{- end -}}
{{- if .Values.imagePullSecret.create -}}
{{- if not (has .Values.imagePullSecret.name $names) -}}
{{- $names = append $names .Values.imagePullSecret.name -}}
{{- end -}}
{{- end -}}
{{- if $names }}
imagePullSecrets:
{{- range $names }}
  - name: {{ . }}
{{- end }}
{{- end -}}
{{- end -}}
