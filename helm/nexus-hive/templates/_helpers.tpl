{{/*
Expand the name of the chart.
*/}}
{{- define "nexus-hive.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to that.
If release name contains chart name it will be used as a full name.
*/}}
{{- define "nexus-hive.fullname" -}}
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

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "nexus-hive.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "nexus-hive.labels" -}}
helm.sh/chart: {{ include "nexus-hive.chart" . }}
{{ include "nexus-hive.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: nexus-hive
{{- end }}

{{/*
Selector labels
*/}}
{{- define "nexus-hive.selectorLabels" -}}
app.kubernetes.io/name: {{ include "nexus-hive.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use.
*/}}
{{- define "nexus-hive.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "nexus-hive.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Image reference (falls back to .Chart.AppVersion when tag is empty)
*/}}
{{- define "nexus-hive.image" -}}
{{- $tag := default .Chart.AppVersion .Values.image.tag -}}
{{- printf "%s:%s" .Values.image.repository $tag -}}
{{- end }}

{{/*
Ollama sidecar image reference
*/}}
{{- define "nexus-hive.ollamaImage" -}}
{{- printf "%s:%s" .Values.ollama.image.repository .Values.ollama.image.tag -}}
{{- end }}

{{/*
Name of the ConfigMap owned by this chart
*/}}
{{- define "nexus-hive.configmapName" -}}
{{- printf "%s-config" (include "nexus-hive.fullname" .) -}}
{{- end }}

{{/*
Name of the PersistentVolumeClaim for the Ollama sidecar
*/}}
{{- define "nexus-hive.ollamaPvcName" -}}
{{- printf "%s-ollama" (include "nexus-hive.fullname" .) -}}
{{- end }}
