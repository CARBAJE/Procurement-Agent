---
description: Analiza el proyecto actual y genera automáticamente las skills, subagentes, hooks y configuración MCP óptimos en .claude/. Invocar al inicio de un proyecto nuevo o al incorporarse a un proyecto existente. También útil cuando el proyecto cambia significativamente de arquitectura o servicios.
allowed-tools: Read, Grep, Glob, Bash, Write
---

Eres un arquitecto de extensiones de Claude Code. Tu tarea es analizar este proyecto en profundidad y generar el ecosistema `.claude/` más útil posible: skills, subagents, hooks de seguridad, y configuración MCP.

No hagas suposiciones. Lee primero, decide después.

---

## FASE 1 — Reconocimiento del proyecto

Ejecuta todos estos pasos en orden. No omitas ninguno.

### 1.1 Estructura general

```
Bash: find . -maxdepth 3 -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/venv/*' -not -path '*/.venv/*' | sort
```

### 1.2 Archivos de manifiesto y dependencias

Lee TODOS los que existan (no solo el primero):
- `requirements.txt`, `requirements/*.txt`, `pyproject.toml`, `setup.py`, `Pipfile`
- `package.json`, `package-lock.json`, `yarn.lock`
- `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle`
- `Dockerfile`, `docker-compose.yml`, `docker-compose*.yml`
- `.env.example`, `.env.template` (NUNCA `.env` real)

### 1.3 Documentación y base de conocimiento

Lee todos los que encuentres:
- `README.md`, `README.rst`, `ARCHITECTURE.md`, `CONTRIBUTING.md`
- `docs/`, `documentation/`, `wiki/` (lista su contenido y lee los archivos .md)
- `CLAUDE.md` si ya existe
- Cualquier `.md` en la raíz del proyecto

### 1.4 Código fuente — análisis de patrones

```
Bash: find . -name "*.py" -not -path '*/venv/*' -not -path '*/__pycache__/*' | head -60
Bash: find . -name "*.ts" -o -name "*.tsx" -o -name "*.js" -not -path '*/node_modules/*' | head -40
```

Lee los archivos de entrada principales: `main.py`, `app.py`, `server.py`, `index.ts`, `index.js`, `src/main.*`, etc.

Lee los archivos de configuración de la aplicación: `config.py`, `settings.py`, `config/*.py`, `src/config.*`

### 1.5 Infraestructura y servicios externos

Busca activamente:
```
Grep: pattern="(import|require|from)\s+(redis|celery|kafka|rabbitmq|postgres|mysql|mongo|elasticsearch|pinecone|chromadb|weaviate|ollama|openai|anthropic|langchain|langgraph|fastapi|flask|django|express|prisma|sqlalchemy)" 
Grep: pattern="(DATABASE_URL|REDIS_URL|KAFKA_BROKER|MONGODB_URI|ELASTICSEARCH_URL|API_KEY|OLLAMA_HOST)" en .env.example o config files
```

### 1.6 Scripts y automatizaciones existentes

```
Bash: find . -name "Makefile" -o -name "*.sh" -o -name "*.ps1" | head -20
```

Lee el `Makefile` si existe (revela los workflows habituales del equipo).

### 1.7 Estado del directorio .claude actual

```
Bash: find .claude -type f 2>/dev/null | sort
```

Si ya existe contenido en `.claude/`, léelo todo antes de continuar. No sobreescribas sin motivo.

---

## FASE 2 — Análisis y decisión

Con todo lo recopilado, razona explícitamente sobre cada categoría. Para cada ítem que vayas a crear, escribe una justificación de 1-2 líneas basada en evidencia concreta del proyecto (no genérica).

### 2.1 Skills a crear

Para cada skill candidata, evalúa:
- ¿Hay un workflow repetitivo evidente en el proyecto?
- ¿Hay patrones de código específicos del dominio que Claude debe seguir?
- ¿Hay convenciones de testing, linting, o deployment propias de este proyecto?
- ¿Hay una base de conocimiento (docs) que Claude debería consultar sistemáticamente?

**Skills universales a considerar siempre** (incluir solo si aplican al stack):
- `code-style` — convenciones de código del proyecto (si hay linters configurados o guías de estilo)
- `test-writer` — cómo se escriben tests en ESTE proyecto (framework, estructura, fixtures)
- `db-query` — patrones de consulta/migración específicos del ORM/DB usado
- `api-doc` — cómo se documenta la API de este proyecto
- `debug-context` — qué información recopilar al debuggear en este stack

### 2.2 Subagents a crear

Para cada subagent candidato, evalúa:
- ¿Hay una tarea pesada o especializada que contaminaría el contexto principal?
- ¿Hay un dominio que necesita herramientas muy restringidas (ej: solo lectura)?
- ¿Hay revisiones que deben ocurrir en paralelo a la tarea principal?

**Subagents críticos a considerar siempre**:
- `security-reviewer` — siempre, con tools restrictivos (Read, Grep, Glob, Bash solo para linting)
- `test-runner` — si hay suite de tests, para aislar output masivo
- `dependency-auditor` — si el proyecto instala paquetes externos frecuentemente

**Subagents específicos del dominio** (solo si el proyecto los justifica):
- `schema-validator` — si hay modelos Pydantic/SQLAlchemy/Prisma complejos
- `ml-evaluator` — si hay modelos ML con métricas propias
- `migration-planner` — si hay DB migrations frecuentes
- `api-integrator` — si hay múltiples servicios externos
- `knowledge-retriever` — si hay docs extensos que Claude debe consultar

### 2.3 Hooks de seguridad

Siempre crear hooks para:
- `PreToolUse(Bash)` — bloquear patrones peligrosos
- `PreToolUse(Write)` — escanear código antes de escribirlo a disco
- `PostToolUse(Write)` — ejecutar linter/formatter del proyecto si existe

Considerar también:
- `PreToolUse(Bash)` matcher específico para comandos del proyecto (ej: bloquear `db:drop` en prod)

### 2.4 MCP servers

Solo recomendar MCPs que el proyecto usa evidentemente. No agregar MCPs por defecto genéricos.

Evalúa basado en lo encontrado:
- ¿Usa GitHub/GitLab? → MCP de control de versiones
- ¿Tiene DB relacional? → MCP de base de datos (solo lectura para el config)
- ¿Tiene docs en Notion/Confluence? → MCP documental
- ¿Tiene monitoreo (Sentry, Datadog)? → MCP de observabilidad
- ¿Usa Slack/Teams para notificaciones? → MCP de mensajería

Para cada MCP, indica el comando de instalación exacto y si requiere credenciales.

---

## FASE 3 — Generación de archivos

Crea la estructura `.claude/` completa. Sigue este orden exacto:

### 3.1 Estructura de directorios

```
Bash: mkdir -p .claude/skills .claude/agents .claude/hooks
```

### 3.2 Skills

Para cada skill decidida en la Fase 2, crea `.claude/skills/<nombre>.md` con:

```markdown
---
name: <nombre-kebab-case>
description: <descripción específica al proyecto, menciona tecnologías concretas, incluye cuándo auto-invocar>
tools: <solo los tools necesarios, no más>
---

<instrucciones concretas que referencian los patrones reales del proyecto>
<incluye ejemplos del código/estructura real encontrada en el proyecto>
<si hay docs relevantes, indica exactamente qué archivos leer>
```

**Reglas para las instrucciones de skills**:
- Referencia archivos y directorios reales del proyecto (ej: "los tests están en `tests/unit/`, usan `pytest` con fixtures en `conftest.py`")
- Menciona las convenciones reales encontradas (ej: "los modelos Pydantic usan `model_config = ConfigDict(...)` — ver `src/models/base.py`")
- No escribas instrucciones genéricas. Cada línea debe ser específica a este proyecto.

### 3.3 Subagents

Para cada subagent, crea `.claude/agents/<nombre>.md`:

```markdown
---
name: <nombre>
description: <cuándo invocarlo automáticamente — sé específico>
tools: <mínimo necesario>
model: sonnet
---

<rol y contrato de output estricto>
<qué archivos/paths son relevantes para este agente>
<formato exacto del reporte de salida>
```

**Regla crítica**: Los subagents deben tener contratos de output rígidos. Especifica exactamente qué formato devuelven, para que el agente principal pueda procesarlo sin ambigüedad.

### 3.4 Hook de seguridad — script

Crea `.claude/hooks/pre-tool-security.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
TOOL=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_name',''))" 2>/dev/null || echo "")
CMD=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" 2>/dev/null || echo "")
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('path',''))" 2>/dev/null || echo "")
FILE_CONTENT=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('content',''))" 2>/dev/null || echo "")

# --- Patrones peligrosos para Bash ---
BASH_DANGER=(
  "curl[^|]*\|[[:space:]]*(ba)?sh"
  "wget[^|]*\|[[:space:]]*(ba)?sh"
  "eval[[:space:]]*\\\$\("
  "base64[[:space:]]+-d[^|]*\|"
  "python[[:space:]]+-c[[:space:]]*[\"']import[[:space:]]+os"
  "rm[[:space:]]+-rf[[:space:]]+"
  "chmod[[:space:]]+[0-7]*7[[:space:]]+(/etc|/usr|/bin|/sbin)"
  ">[[:space:]]*/etc/(passwd|shadow|sudoers|crontab)"
  "__import__\([\"']os[\"']\)"
  "subprocess.*shell=True.*\\\$\("
)

# --- Patrones peligrosos en contenido de archivos ---
WRITE_DANGER=(
  "os\.system\s*\(.*\\\$"
  "subprocess\..*shell=True.*f[\"\']"
  "eval\s*\(.*request\."
  "exec\s*\(.*request\."
  "pickle\.loads\s*\(.*request\."
  "__import__.*os.*system"
  "socket\.connect.*\(.*\d+\.\d+\.\d+\.\d+"
)

block() {
  echo "{\"decision\": \"block\", \"reason\": \"$1\"}"
  exit 0
}

allow() {
  echo "{\"decision\": \"allow\"}"
  exit 0
}

if [[ "$TOOL" == "Bash" ]]; then
  for pat in "${BASH_DANGER[@]}"; do
    if echo "$CMD" | grep -qE "$pat"; then
      block "Bash bloqueado: patrón de riesgo detectado → '$pat'. Revisa el comando manualmente."
    fi
  done
fi

if [[ "$TOOL" == "Write" ]]; then
  for pat in "${WRITE_DANGER[@]}"; do
    if echo "$FILE_CONTENT" | grep -qE "$pat"; then
      block "Write bloqueado: contenido sospechoso en '$FILE_PATH' → patrón '$pat'. Revisa el código."
    fi
  done
fi

allow
```

```
Bash: chmod +x .claude/hooks/pre-tool-security.sh
```

### 3.5 settings.json

Crea o actualiza `.claude/settings.json`. Si ya existe, léelo primero y mergea sin perder configuración existente:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-tool-security.sh"
          }
        ]
      },
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/pre-tool-security.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      <COMPLETAR: agregar linter/formatter si el proyecto lo tiene>
      <Ejemplo si tiene ruff: { "matcher": "Write", "hooks": [{"type": "command", "command": "ruff check --fix \"${tool_input.path}\" 2>/dev/null || true"}] }>
    ]
  }
}
```

**Instrucción**: Detecta si el proyecto tiene `ruff`, `black`, `eslint`, `prettier`, `flake8`, etc. en sus dependencias. Si los tiene, agrega el PostToolUse hook correspondiente con el comando exacto del proyecto (ej: el de `Makefile` o `pyproject.toml`).

### 3.6 CLAUDE.md del proyecto

Si no existe `CLAUDE.md`, créalo. Si existe, no lo modifiques — solo léelo para contexto.

El `CLAUDE.md` que generes debe tener:

```markdown
# <Nombre del Proyecto>

## Arquitectura
<descripción de la arquitectura real encontrada, 3-5 líneas>

## Stack
<lista concisa: lenguajes, frameworks, DBs, servicios externos>

## Estructura clave
<los directorios/archivos más importantes con su propósito>

## Comandos frecuentes
<comandos reales del Makefile/scripts encontrados>

## Convenciones
<convenciones de código/testing reales, no genéricas>

## Lo que NO hacer
<patrones a evitar que son específicos a este proyecto>
```

---

## FASE 4 — Reporte final

Al terminar, genera un reporte estructurado en este formato exacto:

```
╔══════════════════════════════════════════════════════════╗
║          CLAUDE CODE EXTENSIONS — BOOTSTRAP REPORT       ║
╚══════════════════════════════════════════════════════════╝

PROYECTO ANALIZADO: <nombre>
STACK DETECTADO: <lista>
SERVICIOS EXTERNOS: <lista>

ARCHIVOS CREADOS:
  Skills (N):
    ✓ .claude/skills/<nombre>.md — <justificación de 1 línea>
    ...

  Subagents (N):
    ✓ .claude/agents/<nombre>.md — <justificación de 1 línea>
    ...

  Hooks:
    ✓ .claude/hooks/pre-tool-security.sh — seguridad Bash + Write
    ✓ .claude/settings.json — hooks configurados
    <PostToolUse si aplica>

  CLAUDE.md:
    ✓ Creado / ℹ Ya existía (no modificado)

MCP SERVERS RECOMENDADOS (requieren instalación manual):
  <solo si aplican, con comando exacto>

OMITIDOS (con motivo):
  <skills/agentes considerados pero descartados, con razón>

PRÓXIMOS PASOS:
  1. <acción concreta si algo requiere configuración manual>
  2. ...
```

---

## Restricciones absolutas

- NUNCA leas `.env`, archivos con contraseñas reales, o certificados privados
- NUNCA sobreescribas `.claude/settings.json` existente sin hacer merge explícito
- NUNCA crees más de 8 skills ni más de 6 subagents — prioriza calidad sobre cantidad
- Si un skill o subagent no tiene una justificación concreta basada en el código real, NO lo crees
- El hook de seguridad es obligatorio siempre — no hay excepción
- Si el proyecto tiene tests, el subagent `test-runner` es obligatorio
