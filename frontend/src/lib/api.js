/* Backend client.

   Every call targets the FastAPI service. The base URL is configurable so the
   deployed frontend can point somewhere other than localhost. */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export class ApiError extends Error {
  constructor(message, { status, detail } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request(path, { signal, ...options } = {}) {
  let response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "content-type": "application/json" },
      signal,
      ...options,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(
      "Cannot reach the Wallerina backend. Is the API running?",
      { status: 0 }
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body; keep the status text.
    }
    throw new ApiError(detail, { status: response.status, detail });
  }

  return response.json();
}

/* A wallet address is the one piece of user input that reaches the chain, so
   it is validated before any request is made. */
export function isValidAddress(address) {
  return /^0x[a-fA-F0-9]{40}$/.test(address?.trim() ?? "");
}

export function health() {
  return request("/health");
}

export function fetchAnalysis(address, { horizonDays = 90, simulations = 10000, refresh = false, signal } = {}) {
  const params = new URLSearchParams({
    horizon_days: String(horizonDays),
    simulations: String(simulations),
  });
  if (refresh) params.set("refresh", "true");

  return request(`/api/analysis/${address}?${params}`, { signal });
}

export function fetchPortfolio(address, { signal } = {}) {
  return request(`/api/portfolio/${address}`, { signal });
}

export function fetchPriceHistory({ symbol, network, address, days = 180, signal } = {}) {
  const params = new URLSearchParams({ days: String(days) });
  if (symbol) params.set("symbol", symbol);
  if (network) params.set("network", network);
  if (address) params.set("address", address);

  return request(`/api/prices/history?${params}`, { signal });
}

export function runSimulation(body, { signal } = {}) {
  return request("/api/simulate", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

export function runScenarios(body, { signal } = {}) {
  return request("/api/simulate/scenarios", {
    method: "POST",
    body: JSON.stringify(body),
    signal,
  });
}

/* Goals. A preset label resolves on the backend with no model call; anything
   else is read by the goal agent when a recommendation is requested. */
export function fetchGoalPresets({ signal } = {}) {
  return request("/api/goals/presets", { signal });
}

export function fetchGoal(address, { signal } = {}) {
  return request(`/api/goal/${address}`, { signal });
}

export function saveGoal(address, goal) {
  return request(`/api/goal/${address}`, {
    method: "PUT",
    body: JSON.stringify({ goal }),
  });
}

/* The full agent pipeline: goal, analysis agents, allocation engine, judgement
   and grounding. A free-text goal adds a model call, so allow up to a minute. */
export function fetchRecommendation(address, { goal, signal } = {}) {
  const params = new URLSearchParams();
  if (goal) params.set("goal", goal);
  return request(`/api/recommendation/${address}?${params}`, { signal });
}

export function fetchRecommendationHistory(address, { limit = 10, signal } = {}) {
  return request(`/api/recommendation/${address}/history?limit=${limit}`, { signal });
}

/**
 * Stream a chat reply as server-sent events.
 *
 * The backend emits one JSON object per `data:` frame: `text` deltas, `tool`
 * notices, `error`, and a final `done`. Each is handed to `onEvent` as it
 * arrives so the UI can render the answer while it is still being written.
 */
export async function streamChat({ walletAddress, message, history = [], onEvent, signal }) {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      wallet_address: walletAddress,
      message,
      history,
    }),
    signal,
  });

  if (!response.ok) {
    let detail = `The assistant is unavailable (${response.status}).`;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // Keep the generic message.
    }
    throw new ApiError(detail, { status: response.status, detail });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; the last chunk may be partial.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data:"));
      if (!line) continue;

      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        // Ignore malformed frames rather than killing the stream.
      }
    }
  }
}

/* Value and risk over time. `backfilled` is today's holdings valued over their
   price history (available at once); `recorded` is what the database saved for
   this wallet, which fills in as the background refresh runs. */
export function fetchPerformanceHistory(address, { recordedDays = 30, signal } = {}) {
  return request(`/api/history/${address}/performance?recorded_days=${recordedDays}`, { signal });
}

export function fetchRiskHistory(address, { recordedDays = 30, signal } = {}) {
  return request(`/api/history/${address}/risk?recorded_days=${recordedDays}`, { signal });
}

/* A heavy simulation is queued rather than run inline: `runSimulation` then
   resolves to a job ({ job_id, status: "queued" }) whose result is fetched
   here once its status is "complete". */
export function fetchSimulationJob(jobId, { signal } = {}) {
  return request(`/api/simulate/jobs/${jobId}`, { signal });
}
