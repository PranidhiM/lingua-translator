
import { useCallback, useEffect, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const languages = [
  { code: "en", name: "English" },
  { code: "hi", name: "Hindi" },
  { code: "te", name: "Telugu" },
];

type Translation = {
  id: number;
  source_language: string;
  target_language: string;
  source_text: string;
  translated_text: string;
  created_at: string;
};

type Analytics = {
  total_translations: number;
  language_pairs: { source: string; target: string; count: number }[];
  daily_activity: { date: string; count: number }[];
};

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");

  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API}${path}`, {
    ...options,
    headers,
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || `Request failed (${response.status})`);
  }

  return data as T;
}

function languageName(code: string) {
  return languages.find((item) => item.code === code)?.name || code;
}

export default function App() {
  const [token, setToken] = useState(
    () => localStorage.getItem("translator_token"),
  );
  const [email, setEmail] = useState(
    () => localStorage.getItem("translator_email") || "",
  );
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [password, setPassword] = useState("");

  const [source, setSource] = useState("en");
  const [target, setTarget] = useState("hi");
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [history, setHistory] = useState<Translation[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);

  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadDashboard = useCallback(async () => {
    if (!token) return;

    try {
      const [items, stats] = await Promise.all([
        request<Translation[]>("/api/history", {}, token),
        request<Analytics>("/api/analytics", {}, token),
      ]);
      setHistory(items);
      setAnalytics(stats);
    } catch (err) {
      const text = err instanceof Error ? err.message : "Unable to load history.";
      setError(text);
    }
  }, [token]);

  useEffect(() => {
    if (token) void loadDashboard();
  }, [token, loadDashboard]);

  async function submitAuth(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);

    try {
      if (authMode === "register") {
        await request("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({
            email: authEmail,
            password,
          }),
        });
        setMessage("Account created. Please log in.");
        setAuthMode("login");
      } else {
        const result = await request<{
          access_token: string;
          email: string;
        }>("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            email: authEmail,
            password,
          }),
        });

        localStorage.setItem("translator_token", result.access_token);
        localStorage.setItem("translator_email", result.email);
        setToken(result.access_token);
        setEmail(result.email);
        setPassword("");
        setMessage("Welcome back!");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  }

  async function translate() {
    setError("");
    setMessage("");

    if (!input.trim()) {
      setError("Enter some text to translate.");
      return;
    }

    if (!token) return;

    setLoading(true);
    try {
      const result = await request<Translation>(
        "/api/translate",
        {
          method: "POST",
          body: JSON.stringify({
            source_language: source,
            target_language: target,
            text: input.trim(),
          }),
        },
        token,
      );

      setOutput(result.translated_text);
      setMessage("Translation saved to your history.");
      await loadDashboard();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Translation failed.");
    } finally {
      setLoading(false);
    }
  }

  function swapLanguages() {
    setSource(target);
    setTarget(source);
    setInput(output);
    setOutput(input);
    setError("");
    setMessage("");
  }

  function logout() {
    localStorage.removeItem("translator_token");
    localStorage.removeItem("translator_email");
    setToken(null);
    setEmail("");
    setHistory([]);
    setAnalytics(null);
    setInput("");
    setOutput("");
    setMessage("You have logged out.");
    setError("");
  }

  async function deleteTranslation(id: number) {
    if (!token) return;
    setError("");

    try {
      await request(`/api/history/${id}`, { method: "DELETE" }, token);
      await loadDashboard();
      setMessage("Translation removed from history.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed.");
    }
  }

  function exportCsv() {
    const columns = [
      "Date",
      "Source Language",
      "Target Language",
      "Original Text",
      "Translated Text",
    ];

    const escapeCsv = (value: string) =>
      `"${value.replace(/"/g, '""')}"`;

    const rows = history.map((item) => [
      item.created_at,
      languageName(item.source_language),
      languageName(item.target_language),
      item.source_text,
      item.translated_text,
    ]);

    const csv = [columns, ...rows]
      .map((row) => row.map((value) => escapeCsv(String(value))).join(","))
      .join("\r\n");

    const url = URL.createObjectURL(
      new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8;" }),
    );

    const link = document.createElement("a");
    link.href = url;
    link.download = "translation-history.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  if (!token) {
    return (
      <main className="auth-screen">
        <section className="auth-card">
          <div className="brand-mark">文</div>
          <p className="eyebrow">YOUR PERSONAL LANGUAGE STUDIO</p>
          <h1>Words connect worlds.</h1>
          <p className="muted">
            Translate naturally, keep your history, and explore your language
            learning data.
          </p>

          <div className="auth-tabs">
            <button
              className={authMode === "login" ? "active" : ""}
              onClick={() => setAuthMode("login")}
              type="button"
            >
              Log in
            </button>
            <button
              className={authMode === "register" ? "active" : ""}
              onClick={() => setAuthMode("register")}
              type="button"
            >
              Create account
            </button>
          </div>

          <form onSubmit={submitAuth} className="auth-form">
            <label htmlFor="email">Email address</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={authEmail}
              onChange={(e) => setAuthEmail(e.target.value)}
              placeholder="you@example.com"
            />

            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete={
                authMode === "login" ? "current-password" : "new-password"
              }
              minLength={8}
              maxLength={72}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
            />

            <button className="primary-btn full-width" disabled={loading}>
              {loading
                ? "Please wait..."
                : authMode === "login"
                  ? "Log in →"
                  : "Create my account →"}
            </button>
          </form>

          {message && <p className="notice">{message}</p>}
          {error && <p className="error">{error}</p>}
          <p className="small muted">Private history · Personal analytics</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="#" aria-label="Lingua home">
          <span className="brand-mark small-mark">文</span>
          <span>lingua<span className="brand-dot">.</span></span>
        </a>

        <nav className="top-nav">
          <a href="#translate">Translate</a>
          <a href="#history">History</a>
          <a href="#analytics">Insights</a>
        </nav>

        <div className="account">
          <span className="avatar">{email.charAt(0).toUpperCase()}</span>
          <span className="account-email">{email}</span>
          <button className="secondary-btn" onClick={logout}>Log out</button>
        </div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">A LITTLE CLOSER, IN EVERY LANGUAGE</p>
          <h1>Say it your way.</h1>
          <p className="muted">
            Thoughtful translations. Your words, always within reach.
          </p>
        </div>
        <div className="hero-decoration" aria-hidden="true">
          <span>こんにちは</span><span>నమస్కారం</span><span>नमस्ते</span>
        </div>
      </section>

      {message && <p className="notice">{message}</p>}
      {error && <p className="error">{error}</p>}

      <section id="translate" className="translator-card">
        <div className="language-bar">
          <label className="language-select">
            <span>FROM</span>
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              {languages.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.name}
                </option>
              ))}
            </select>
          </label>

          <button
            className="swap-btn"
            onClick={swapLanguages}
            type="button"
            aria-label="Swap languages"
            title="Swap languages"
          >
            ⇄
          </button>

          <label className="language-select">
            <span>TO</span>
            <select value={target} onChange={(e) => setTarget(e.target.value)}>
              {languages.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="translation-panels">
          <div className="text-panel">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value.slice(0, 5000))}
              placeholder="Type or paste your text here..."
              maxLength={5000}
              aria-label="Text to translate"
            />
            <div className="panel-footer">
              <span>{input.length}/5000 characters</span>
              <button className="text-btn" onClick={() => setInput("")}>
                Clear
              </button>
            </div>
          </div>

          <div className="text-panel output-panel">
            <div className="translated-text">
              {output || "Your translation will appear here..."}
            </div>
            <div className="panel-footer">
              <span>{output.length} characters</span>
              <button
                className="text-btn"
                disabled={!output}
                onClick={() => {
                  void navigator.clipboard.writeText(output).then(
                    () => setMessage("Translation copied."),
                    () => setError("Could not access clipboard."),
                  );
                }}
              >
                Copy text
              </button>
            </div>
          </div>
        </div>

        <div className="translate-action">
          <span className="muted small">
            AI-powered · Saved privately to your account
          </span>
          <button
            className="primary-btn"
            onClick={() => void translate()}
            disabled={loading || !input.trim()}
          >
            {loading ? "Working..." : "Translate text ↗"}
          </button>
        </div>
      </section>

      <section className="stats-grid" id="analytics">
        <article className="stat-card">
          <span className="stat-icon">文</span>
          <p>Total translations</p>
          <strong>{analytics?.total_translations ?? "—"}</strong>
          <span className="small muted">Saved to your history</span>
        </article>
        <article className="stat-card">
          <span className="stat-icon">↔</span>
          <p>Language pairs</p>
          <strong>{analytics?.language_pairs.length ?? "—"}</strong>
          <span className="small muted">Unique combinations used</span>
        </article>
        <article className="stat-card">
          <span className="stat-icon">▥</span>
          <p>Active days</p>
          <strong>{analytics?.daily_activity.length ?? "—"}</strong>
          <span className="small muted">Days with translations</span>
        </article>
      </section>

      <section className="content-grid">
        <article className="content-card" id="history">
          <div className="section-heading">
            <div>
              <p className="eyebrow">YOUR WORDS, KEPT SAFE</p>
              <h2>Recent translations</h2>
            </div>
            <button
              className="secondary-btn"
              onClick={exportCsv}
              disabled={history.length === 0}
            >
              ↓ Export CSV
            </button>
          </div>

          {history.length === 0 ? (
            <p className="empty-state">
              Your saved translations will appear here after your first
              translation.
            </p>
          ) : (
            <div className="history-list">
              {history.map((item) => (
                <article className="history-item" key={item.id}>
                  <div className="history-language">
                    {languageName(item.source_language)} →{" "}
                    {languageName(item.target_language)}
                    <span>{new Date(item.created_at).toLocaleString()}</span>
                  </div>
                  <p>{item.source_text}</p>
                  <p className="history-result">{item.translated_text}</p>
                  <button
                    className="text-btn delete-btn"
                    onClick={() => void deleteTranslation(item.id)}
                  >
                    Delete
                  </button>
                </article>
              ))}
            </div>
          )}
        </article>

        <aside className="content-card">
          <p className="eyebrow">DATA SCIENCE INSIGHTS</p>
          <h2>Your language patterns</h2>
          <p className="muted">
            Explore how often you translate between different languages.
          </p>

          {!analytics?.language_pairs.length ? (
            <p className="empty-state">Your language insights will grow here.</p>
          ) : (
            <div className="pair-list">
              {analytics.language_pairs.map((pair) => {
                const max = Math.max(
                  ...analytics.language_pairs.map((p) => p.count),
                  1,
                );
                return (
                  <div className="pair-item" key={`${pair.source}-${pair.target}`}>
                    <div className="pair-label">
                      <span>{pair.source} → {pair.target}</span>
                      <strong>{pair.count}</strong>
                    </div>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{ width: `${(pair.count / max) * 100}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="activity-block">
            <h3>Daily activity</h3>
            {analytics?.daily_activity.slice(-7).map((day) => (
              <div className="activity-row" key={day.date}>
                <span>{day.date}</span>
                <span>{day.count} translations</span>
              </div>
            ))}
          </div>
        </aside>
      </section>

      <footer className="footer">
        <span>lingua. · Your personal language studio</span>
        <span>Built with AI and data science</span>
      </footer>
    </main>
  );
}
