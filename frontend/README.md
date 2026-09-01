# Insight Platform - Release Management Portal

A modern enterprise React web application for managing software release requests, approvals, and deployment workflows.

## Features

- **Release Dashboard** — Table view of all release requests with search
- **New Release Modal** — Create release requests with manual text inputs (no dropdowns)
- **Release Details** — Release info table, workflow progress bar, and audit-style workflow activity log
- **Approval Queue** — Dedicated page for L3 approvals with Approve/Reject actions
- **Dynamic Workflow** — Workflow rows append as stages progress (audit log style)

## Tech Stack

- React 19 + TypeScript
- Vite
- React Router

## Getting Started

```bash
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

## Build

```bash
npm run build
```

## Usage Flow

1. Click **+ New Release** to create a release request
2. Submit the form — release appears in the dashboard with status **PR Request Raised**
3. Go to **Approval Queue** to Approve or Reject pending releases
4. Click **View Details** to see workflow progress and activity log
5. After approval, CI/CD stages auto-advance when viewing the Release Details page

## Design

- Light theme with white background and blue primary color
- Table-driven UI (no cards, charts, or dropdowns)
- Status badges: Pending (orange), Running (blue), Completed (green), Rejected (red), Failed (dark red)
