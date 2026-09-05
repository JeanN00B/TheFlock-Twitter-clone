# Technical Challenge — Twitter Clone
**The Flock · Managed Software Teams**

---

## 1. Overview

This challenge evaluates your ability to develop a complete full-stack application: a functional clone of Twitter/X. The domain is familiar to everyone, which lets you focus on technical quality and architectural decision-making without wasting time understanding the business.

> **Important:** We expect you to use AI/agentic coding tools (Cursor, Codex, Claude Code, GitHub Copilot, or similar) throughout development. A core part of the evaluation is your ability to direct these tools effectively to produce professional-quality software.

---

## 2. Technology Stack

The stack is entirely your choice. You can use any combination of languages, frameworks, and databases you consider appropriate. The only requirements:

- At least one backend with a relational database (PostgreSQL or SQLite preferred).
- At least one web frontend with client-side or server-side rendering.
- **Custom authentication:** do not use third-party solutions like Firebase Auth or Supabase Auth.
- Your stack choice must be justified in the README.

**Examples:** Rails + React, Django + HTMX, .NET MVC + Razor + Alpine.js, Node.js + Vue, Go + Templ, Laravel + Livewire.

> The stack itself is not graded — the execution is.

---

## 3. Important: We Evaluate the Process

We will analyze not only the final result, but the entire development process. In particular:

- **The GitHub repository:** must be public (or shared with the evaluators). The full development history must be visible.
- **Commits:** do not squash. We want to see every individual commit, its message, its size, and its coherence. Commits should tell the story of how you built the application.
- **The evolution:** we expect a logical progression, from initial scaffolding to complete features. Not a single giant commit at the end.
- **AI usage patterns:** good use of agentic coding shows in pattern consistency, solid structure from the start, and iteration speed.

---

## 4. Required Features

### 4.1 Authentication

- User registration (email + password at minimum).
- Login / Logout.
- Route protection: authenticated actions must require a valid session.
- Basic user profile: unique username, bio, and avatar placeholder.

### 4.2 Tweets

- Create a tweet (text, maximum 280 characters).
- Delete your own tweet.
- Timeline: show tweets from followed users, ordered chronologically.
- Pagination or infinite scroll on the timeline.

### 4.3 Social Interactions

- Follow / Unfollow users.
- Like / Unlike tweets.
- Visible like counter on each tweet.
- Followers and following list on the user profile.

### 4.4 Search

- Basic user search by name or username.

### 4.5 Responsive Design

- The application must be fully responsive and usable on mobile.
- **Mobile-first approach:** design must be conceived for mobile first and scale up to desktop.
- Minimum breakpoints: mobile (< 640px), tablet (640–1024px), desktop (> 1024px).

---

## 5. Technical Requirements

### 5.1 Testing

Minimum backend test coverage of 80%. This includes:

- Unit tests for models and validations.
- Integration tests for critical API endpoints.
- At least one end-to-end test for the authentication flow.

On the frontend, include at least integration tests for the main flows (login, create tweet, follow).

### 5.2 Seed Data

- The project must include a seed that generates realistic data: at least 10 users with tweets, follows, and cross-likes.
- It must be possible to start the project and see content immediately after running the seed.

### 5.3 README and Runbook

> **The Runbook is mandatory** and will be the first thing evaluators read. If the application cannot be started by following the Runbook without additional manual intervention, points will be deducted directly from the Functionality score.

**Runbook (Setup & Operations):**

- Prerequisites: exact runtime versions, tools, and required dependencies (e.g. Node 20, Ruby 3.3, .NET 8, Docker 25, etc.).
- Installation steps: exact commands, in order, to clone the repo and get it ready to run. No implicit steps or "set up your environment".
- How to run the data seed.
- How to start the application in development mode.
- How to run the full test suite.
- Required environment variables: full list with descriptions and example values (a `.env.example` file is mandatory).
- Sample access credentials to test the app once running (at least one seed user with email and password).

**Technical decisions:**

- Why you chose the stack you chose.
- How you modeled the timeline and the follows graph.
- How you handled authentication.
- Known trade-offs and limitations.
- What AI tools you used and how you leveraged them.

---

## 6. Optional Features (Bonus)

Pick at least one or two of the following. These add points and signal your ability to handle additional complexity with AI tools:

- **Real-time updates:** live timeline updates (WebSockets or SSE).
- **Image uploads:** allow attaching an image to a tweet.
- **Reply threads:** replies to tweets with thread visualization.
- **Notifications:** basic notification system (new follow, like on your tweet, etc.). _Note: this feature is intentionally ambiguous — design decisions are part of the evaluation._
- **Docker:** docker-compose that brings up the entire stack with a single command.

---

## 7. Delivery

### 7.1 Format

- **GitHub repository:** create a repository (public or with access for the evaluators) and share the link.
- **No squash commits:** the full history must be visible. A single commit with all the code is not accepted.
- **Main branch:** the delivered code must be on `main` or `master`.

### 7.2 Deadline

The deadline is **72 calendar hours** from when you receive this document. If you need an extension, communicate it in advance.

### 7.3 What we expect to see in the repo

- **First commit:** project scaffolding.
- **Progressive commits:** features implemented one by one, with descriptive messages.
- **Testing commits:** tests added alongside features, not all at the end.
- **Last commits:** polish, documentation, and cleanup.

---

## 8. Evaluation Rubric

| Criterion | Weight | What we evaluate |
|---|---|---|
| **Functionality** | 25% | All required features work correctly. The app is usable end to end. |
| **Code quality** | 20% | Clean, consistent, well-organized code. Clear naming. Patterns appropriate to the chosen stack. |
| **Testing** | 25% | Adequate backend coverage (85%+). Meaningful frontend tests. Tests that actually validate logic, not empty tests. |
| **Development process** | 15% | Coherent commit history. Logical progression. Evidence of good AI tool usage. |
| **Documentation** | 10% | Complete README with an operational Runbook. Architecture decisions explained. Clear setup instructions. |
| **Bonus features** | 5% | Optional features correctly implemented. Extra points for complexity and quality. |

---

## 9. Final Note

This challenge is designed to be completed with the assistance of agentic coding tools. The scope is intentionally broad to evaluate your ability to direct these tools effectively, make technical decisions, and deliver professional-quality software within a limited timeframe.

We are not looking for perfection — we are looking for **intelligent pragmatism**: knowing what to delegate to AI, what to review manually, and how to iterate quickly without sacrificing quality.

Keep in mind that the stack choice is part of the evaluation — not for the stack itself, but for how you justify it and how you execute it.

---

**Good luck!**