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

{{/* The data volume's claim: the operator's existingClaim, or the chart's own. */}}
{{- define "raiju.claimName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- printf "%s-data" (include "raiju.fullname" .) }}
{{- end }}
{{- end }}

{{/* Non-empty when the data volume is a claim that one node mounts at a time (ReadWriteOnce or ReadWriteOncePod). */}}
{{- define "raiju.singleWriter" -}}
{{- if and .Values.persistence.enabled (not (has "ReadWriteMany" .Values.persistence.accessModes)) }}true{{ end }}
{{- end }}

{{/* Non-empty when every replica mounts the same files at /app/data (a ReadWriteMany claim). */}}
{{- define "raiju.sharedData" -}}
{{- if and .Values.persistence.enabled (has "ReadWriteMany" .Values.persistence.accessModes) }}true{{ end }}
{{- end }}

{{/* config.json as rendered: the values' config, with cluster.config_sync defaulted when a cluster is on
(docs/operations.md): "file" when the replicas share the data volume, "pull" when each has its own. */}}
{{- define "raiju.config" -}}
{{- $cfg := deepCopy .Values.config }}
{{- $cl := get $cfg "cluster" }}
{{- if and (kindIs "map" $cl) (get $cl "enabled") }}
{{- if not (hasKey $cl "config_sync") }}
{{- $_ := set $cl "config_sync" (ternary "file" "pull" (eq (include "raiju.sharedData" .) "true")) }}
{{- end }}
{{- if and .Values.cluster.secret.existingSecret (not (get $cl "secret")) }}
{{- $_ := set $cl "secret" "env.RAIJU_CLUSTER_SECRET" }}
{{- end }}
{{- if and (gt (int .Values.cluster.listenPort) 0) (not (hasKey $cl "listen_port")) }}
{{- $_ := set $cl "listen_port" (int .Values.cluster.listenPort) }}
{{- $_ := set $cl "bind" "0.0.0.0" }}
{{- end }}
{{- if and .Values.cluster.serveMetrics (not (hasKey $cl "serve_metrics")) }}
{{- $_ := set $cl "serve_metrics" true }}
{{- end }}
{{- end }}
{{- if .Values.metricsToken.existingSecret }}
{{- $server := default dict (get $cfg "server") }}
{{- if not (hasKey $server "metrics_token") }}
{{- $_ := set $server "metrics_token" "env.RAIJU_METRICS_TOKEN" }}
{{- end }}
{{- $_ := set $cfg "server" $server }}
{{- end }}
{{- toJson $cfg }}
{{- end }}

{{/* The cluster listener's port when the rendered config has clustering on and a listen_port, else empty. */}}
{{- define "raiju.clusterPort" -}}
{{- $cfg := include "raiju.config" . | fromJson }}
{{- $cl := get $cfg "cluster" }}
{{- if and (kindIs "map" $cl) (get $cl "enabled") (hasKey $cl "listen_port") }}{{ get $cl "listen_port" | int }}{{ end }}
{{- end }}

{{/* Non-empty when /metrics is served on the cluster listener (cluster.serve_metrics with a cluster port). */}}
{{- define "raiju.metricsOnCluster" -}}
{{- $cfg := include "raiju.config" . | fromJson }}
{{- $cl := get $cfg "cluster" }}
{{- if and (include "raiju.clusterPort" .) (get $cl "serve_metrics") }}true{{ end }}
{{- end }}

{{/* The port Prometheus scrapes /metrics on: the cluster port with serveMetrics, the main port otherwise. */}}
{{- define "raiju.metricsPort" -}}
{{- if include "raiju.metricsOnCluster" . }}{{ include "raiju.clusterPort" . }}{{ else }}{{ .Values.port }}{{ end }}
{{- end }}

{{/* Settings the chart refuses: a single-writer claim with more than one pod, an unknown configMode, and a kill
timeout shorter than the drain (the preStop sleep, server.shutdown_delay_seconds, server.shutdown_grace_seconds and
about 5 s to send what is queued). */}}
{{- define "raiju.validate" -}}
{{- if and (include "raiju.singleWriter" .) (or .Values.autoscaling.enabled (gt (int .Values.replicaCount) 1)) }}
{{- fail "persistence: a ReadWriteOnce volume serves one replica. For several, use ReadWriteMany storage (persistence.accessModes) or persistence.enabled=false with configMode=always; see deploy/README.md" }}
{{- end }}
{{- if not (has .Values.configMode (list "ifAbsent" "always")) }}
{{- fail (printf "configMode must be ifAbsent or always, not %q" .Values.configMode) }}
{{- end }}
{{- $cl := get .Values.config "cluster" }}
{{- if and (kindIs "map" $cl) (get $cl "enabled") }}
{{- $sec := toString (default "" (get $cl "secret")) }}
{{- if and (eq $sec "") (not .Values.cluster.secret.existingSecret) }}
{{- fail "config.cluster.enabled needs a cluster secret: set cluster.secret.existingSecret (a Secret holding RAIJU_CLUSTER_SECRET, at least 32 bytes)" }}
{{- end }}
{{- if and (ne $sec "") (not (hasPrefix "env." $sec)) }}
{{- fail "config.cluster.secret must be an env.NAME reference: the config is a ConfigMap; keep the value in a Secret (cluster.secret.existingSecret)" }}
{{- end }}
{{- end }}
{{- $server := default dict (get .Values.config "server") }}
{{- $grace := 25.0 }}
{{- if hasKey $server "shutdown_grace_seconds" }}{{ $grace = float64 (get $server "shutdown_grace_seconds") }}{{ end }}
{{- $delay := 0.0 }}
{{- if hasKey $server "shutdown_delay_seconds" }}{{ $delay = float64 (get $server "shutdown_delay_seconds") }}{{ end }}
{{- $need := addf (float64 .Values.preStopSleepSeconds) $delay $grace 5.0 }}
{{- if lt (float64 .Values.terminationGracePeriodSeconds) $need }}
{{- fail (printf "terminationGracePeriodSeconds (%v) must be at least preStopSleepSeconds + server.shutdown_delay_seconds + server.shutdown_grace_seconds + 5 (%v)" .Values.terminationGracePeriodSeconds $need) }}
{{- end }}
{{- end }}
