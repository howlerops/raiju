{{/* Chart name, truncated to the Kubernetes name limit. */}}
{{- define "raiju.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Release-scoped name: <release>-<chart>, unless the release name already has it. */}}
{{- define "raiju.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "raiju.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "raiju.selectorLabels" -}}
app.kubernetes.io/name: {{ include "raiju.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "raiju.labels" -}}
helm.sh/chart: {{ include "raiju.chart" . }}
{{ include "raiju.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "raiju.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{- define "raiju.configMapName" -}}
{{- printf "%s-config" (include "raiju.fullname" .) }}
{{- end }}

{{/* Secret read by envFrom: the operator's existingSecret, or the chart's own. */}}
{{- define "raiju.secretName" -}}
{{- if .Values.existingSecret }}
{{- .Values.existingSecret }}
{{- else }}
{{- printf "%s-providers" (include "raiju.fullname" .) }}
{{- end }}
{{- end }}

{{/* Non-empty when the pod gets an envFrom Secret (existing or rendered). */}}
{{- define "raiju.hasSecret" -}}
{{- if or .Values.existingSecret (not (empty .Values.providerSecrets)) }}true{{ end }}
{{- end }}
