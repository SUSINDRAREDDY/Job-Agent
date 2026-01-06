# Job Agent

Browser automation agent for job searching and applying. Built with **LangGraph multi-agent orchestration** for intelligent, modular task execution.

## Architecture

This project uses a **LangGraph-based multi-agent orchestration** system where specialized subagents collaborate to accomplish complex job application workflows:

```
┌─────────────────────────────────────────────────────┐
│                 Orchestrator Agent                  │
│   Coordinates workflow, delegates to subagents      │
└───────────────────┬─────────────────────────────────┘
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
┌───────────────┐       ┌───────────────┐
│ Browser Agent │       │  Apply Agent  │
│  Navigation,  │       │ Form filling, │
│   scanning    │       │  submission   │
└───────────────┘       └───────────────┘
```

| Agent | Description |
|-------|-------------|
| **Orchestrator** | Main agent that receives user intent, plans tasks, and delegates to subagents |
| **Browser Agent** | General-purpose browser automation using Playwright - navigation, clicking, typing, scrolling |
| **Apply Agent** | Specialized for filling job application forms and submitting applications |

Uses Playwright for reliable automation and LLMs for intelligent navigation.

## Demo

https://github.com/user-attachments/assets/demo.mp4

<video src="demo/demo.mp4" controls width="100%"></video>

## Features

- [x] ~~Applying filters and typing job roles~~
- [x] ~~Fetching list of job links and pagination~~
- [x] ~~Going through each job and applying/filling forms~~
- [ ] Creating tailored resumes and cover letters for each job (file upload tools)
- [ ] Web research for company info and sending cold emails
- [ ] Supabase integration to track application data (MCP tool)

> **Model:** Using GLM-4.7 (zhipu/glm-4.7) as the default model.

## Quick Start

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run
python run_agent.py "AI internship remote" "https://www.indeed.com/jobs"
```

## Requirements

- Python 3.10+
- Chrome browser
- OpenRouter API key

## Configuration

Copy `.env.example` to `.env` and add your keys:

```bash
OPENROUTER_API_KEY=sk-or-v1-xxxxx  # Required
DEEPSEEK_API_KEY=sk-xxxxx          # Optional
LANGCHAIN_API_KEY=lsv2_pt_xxxxx    # Optional (for tracing)
```

### Model Selection

Edit `agent_logic/config.py` to change models:

```python
MAIN_MODEL = "zhipu/glm-4.7"          # Default
VISION_MODEL = "x-ai/grok-4.1-fast"  # For screenshots
```

## Usage

### Basic Search
```bash
python run_agent.py "software engineer" "https://www.indeed.com/jobs"
```

### With Filters
```bash
python run_agent.py "AI internship salary $40/hr remote" "https://www.indeed.com/jobs"
python run_agent.py "python developer $100k" "https://www.linkedin.com/jobs"
```

### Options
```bash
python run_agent.py "query" "url" --max-jobs 5
```

## User Data

Create `user_data.json` to auto-fill application forms:

```json
{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john@example.com",
  "phone": "555-123-4567",
  "linkedin": "https://linkedin.com/in/johndoe",
  "years_experience": "3"
}
```

## Project Structure

```
Job_Agent/
├── run_agent.py          # Entry point
├── config.py             # LLM config
├── prompts.py            # Agent prompts
├── models/               # LLM wrappers
│   ├── minimax_reasoner.py
│   ├── glm_reasoner.py
│   └── deepseek_reasoner.py
├── browser/              # Browser automation
│   ├── playwright_tools.py
│   ├── playwright_manager.py
│   ├── accessibility_scanner.py
│   └── scripts/
├── agent/                # Agent logic
│   ├── browser_agent.py
│   ├── intent_parser.py
│   └── reasoning_callback.py
└── logs/
```

## Browser Connection

The agent connects to Chrome via remote debugging:

```bash
# Start Chrome with debugging enabled
./launch_agent_browser.sh

# Then run the agent
python run_agent.py "your query" "https://indeed.com/jobs"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Failed to connect to Chrome" | Run `./launch_agent_browser.sh` first |
| "Bot detection" | Use logged-in Chrome session |
| "Element not found" | Increase wait time or check page loaded |

## License

MIT
