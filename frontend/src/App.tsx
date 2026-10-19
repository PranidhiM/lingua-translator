import { useCallback, useEffect, useState, type FormEvent } from "react";
import "./App.css";


const API =
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";


type AuthMode = "login" | "register" | "forgot";


type Translation = {
 id: number;
 source_language: string;
 target_language: string;
 source_text: string;
 translated_text: string;
 created_at: string;
};


type RegistrationStats = {
  total_registered_users: number;
  registrations_by_day: { date: string; count: number }[];
  recent_users: {
    id: number;
    email: string;
    registered_at: string;
  }[];
};

type Analytics = {
 total_translations: number;
 language_pairs: {
   source: string;
   target: string;
   count: number;
 }[];
 daily_activity: {
   date: string;
   count: number;
 }[];
};


const languages = [
 { code: "en", name: "English" },
 { code: "hi", name: "Hindi" },
 { code: "te", name: "Telugu" },
];


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
   const detail = data.detail;
   const errorMessage =
     typeof detail === "string"
       ? detail
       : `Request failed (${response.status})`;


   throw new Error(errorMessage);
 }


 return data as T;
}


function languageName(code: string): string {
 return languages.find((item) => item.code === code)?.name || code;
}


export default function App() {

 const [token, setToken] = useState<string | null>(
   () => localStorage.getItem("translator_token"),
 );


 const [email, setEmail] = useState(
   () => localStorage.getItem("translator_email") || "",
 );


 const [authMode, setAuthMode] = useState<AuthMode>("login");


 const [resetToken, setResetToken] = useState(
   () =>
     new URLSearchParams(window.location.search).get("reset_token") || "",
 );


 const [newPassword, setNewPassword] = useState("");
 const [authEmail, setAuthEmail] = useState("");
 const [password, setPassword] = useState("");


 const [source, setSource] = useState("en");
 const [target, setTarget] = useState("hi");
 const [input, setInput] = useState("");
 const [output, setOutput] = useState("");


 const [history, setHistory] = useState<Translation[]>([]);
 const [analytics, setAnalytics] = useState<Analytics | null>(null);
 const [registrationStats, setRegistrationStats] =
   useState<RegistrationStats | null>(null);
 const [adminError, setAdminError] = useState("");


 const [loading, setLoading] = useState(false);
 const [message, setMessage] = useState("");
 const [error, setError] = useState("");


 // LOAD TRANSLATION HISTORY AND ANALYTICS
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
     setError(
       err instanceof Error ? err.message : "Unable to load history.",
     );
   }
 }, [token]);


 useEffect(() => {
   if (token && !resetToken) {
     void loadDashboard();
   }
 }, [token, resetToken, loadDashboard]);


 // LOAD REGISTERED-USER STATISTICS (ADMIN ENDPOINT)
 async function loadRegistrations() {
   if (!token) return;

   setAdminError("");

   try {
     const result = await request<RegistrationStats>(
       "/api/admin/registrations",
       {},
       token,
     );
     setRegistrationStats(result);
   } catch (err) {
     setAdminError(
       err instanceof Error
         ? err.message
         : "Unable to load registrations.",
     );
   }
 }

 // LOGIN, REGISTER AND FORGOT PASSWORD
 async function submitAuth(event: FormEvent<HTMLFormElement>) {
   event.preventDefault();
   setError("");
   setMessage("");
   setLoading(true);


   try {
     if (authMode === "forgot") {
       await request("/api/auth/forgot-password", {
         method: "POST",
         body: JSON.stringify({
           email: authEmail.trim(),
         }),
       });


       setMessage(
         "If an account exists for that email, a reset link will be sent.",
       );
       return;
     }


     if (authMode === "register") {
       await request("/api/auth/register", {
         method: "POST",
         body: JSON.stringify({
           email: authEmail.trim(),
           password,
         }),
       });


       setMessage("Account created. Please log in.");
       setPassword("");
       setAuthMode("login");
       return;
     }


     const result = await request<{
       access_token: string;
       email: string;
     }>("/api/auth/login", {
       method: "POST",
       body: JSON.stringify({
         email: authEmail.trim(),
         password,
       }),
     });


     localStorage.setItem("translator_token", result.access_token);
     localStorage.setItem("translator_email", result.email);


     setToken(result.access_token);
     setEmail(result.email);
     setPassword("");
     setMessage("Welcome back!");
   } catch (err) {
     setError(
       err instanceof Error ? err.message : "Authentication failed.",
     );
   } finally {
     setLoading(false);
   }
 }


 // RESET PASSWORD FROM EMAIL LINK
 async function submitReset(event: FormEvent<HTMLFormElement>) {
   event.preventDefault();
   setError("");
   setMessage("");


   if (!resetToken) {
     setError("The password reset token is missing.");
     return;
   }


   if (newPassword.length < 8 || newPassword.length > 72) {
     setError("Password must contain 8 to 72 characters.");
     return;
   }


   setLoading(true);


   try {
     await request("/api/auth/reset-password", {
       method: "POST",
       body: JSON.stringify({
         token: resetToken,
         new_password: newPassword,
       }),
     });


     setMessage("Password reset successfully. Please log in.");
     setResetToken("");
     setNewPassword("");
     setPassword("");
     setAuthMode("login");


     // Remove the reset token from the browser URL.
     window.history.replaceState({}, "", window.location.pathname);
   } catch (err) {
     setError(
       err instanceof Error ? err.message : "Password reset failed.",
     );
   } finally {
     setLoading(false);
   }
 }


 // TRANSLATE TEXT
 async function translate() {
   setError("");
   setMessage("");


   if (!input.trim()) {
     setError("Enter some text to translate.");
     return;
   }


   if (source === target) {
     setError("Choose two different languages.");
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
     setError(
       err instanceof Error ? err.message : "Translation failed.",
     );
   } finally {
     setLoading(false);
   }
 }


 // SWAP SOURCE AND TARGET LANGUAGES
 function swapLanguages() {
   setSource(target);
   setTarget(source);
   setInput(output);
   setOutput(input);
   setError("");
   setMessage("");
 }


 // LOG OUT
 function logout() {
   localStorage.removeItem("translator_token");
   localStorage.removeItem("translator_email");


   setToken(null);
   setEmail("");
   setHistory([]);
   setAnalytics(null);
   setInput("");
   setOutput("");
   setPassword("");
   setAuthEmail("");
   setAuthMode("login");
   setMessage("You have logged out.");
   setError("");
 }


 // DELETE A SAVED TRANSLATION
 async function deleteTranslation(id: number) {
   if (!token) return;


   setError("");
   setMessage("");


   try {
     await request(`/api/history/${id}`, { method: "DELETE" }, token);


     await loadDashboard();
     setMessage("Translation removed from history.");
   } catch (err) {
     setError(
       err instanceof Error ? err.message : "Delete failed.",
     );
   }
 }


 // EXPORT TRANSLATION HISTORY TO CSV
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
     new Blob(["\uFEFF" + csv], {
       type: "text/csv;charset=utf-8;",
     }),
   );


   const link = document.createElement("a");
   link.href = url;
   link.download = "translation-history.csv";
   document.body.appendChild(link);
   link.click();
   link.remove();


   URL.revokeObjectURL(url);
 }


 // PASSWORD RESET SCREEN
 // This must appear before the normal login screen.
 if (resetToken) {
   return (
     <main className="auth-screen">
       <section className="auth-card">
         <div className="brand-mark">文</div>


         <p className="eyebrow">ACCOUNT RECOVERY</p>
         <h1>Create a new password.</h1>


         <p className="muted">
           Choose a new password for your Translator account.
         </p>


         <form onSubmit={submitReset} className="auth-form">
           <label htmlFor="new-password">New password</label>


           <input
             id="new-password"
             type="password"
             autoComplete="new-password"
             minLength={8}
             maxLength={72}
             required
             value={newPassword}
             onChange={(e) => setNewPassword(e.target.value)}
             placeholder="At least 8 characters"
           />


           <button
             className="primary-btn full-width"
             disabled={loading}
             type="submit"
           >
             {loading ? "Resetting..." : "Reset password →"}
           </button>
         </form>


         {message && <p className="notice">{message}</p>}
         {error && <p className="error">{error}</p>}


         <button
           type="button"
           className="text-btn"
           onClick={() => {
             setResetToken("");
             setNewPassword("");
             setMessage("");
             setError("");
             window.history.replaceState(
               {},
               "",
               window.location.pathname,
             );
           }}
         >
           Back to login
         </button>
       </section>
     </main>
   );
 }


 // LOGIN, REGISTER AND FORGOT PASSWORD SCREEN
 if (!token) {
   return (
     <main className="auth-screen">
       <section className="auth-card">
         <div className="brand-mark">文</div>


         <p className="eyebrow">YOUR PERSONAL LANGUAGE STUDIO</p>


         <h1>
           {authMode === "forgot"
             ? "Recover your account."
             : "Words connect worlds."}
         </h1>


         <p className="muted">
           {authMode === "forgot"
             ? "Enter your email address to request a password reset link."
             : "Translate naturally, keep your history, and explore your language learning data."}
         </p>


         {authMode !== "forgot" && (
           <div className="auth-tabs">
             <button
               className={authMode === "login" ? "active" : ""}
               onClick={() => {
                 setAuthMode("login");
                 setMessage("");
                 setError("");
               }}
               type="button"
             >
               Log in
             </button>


             <button
               className={authMode === "register" ? "active" : ""}
               onClick={() => {
                 setAuthMode("register");
                 setMessage("");
                 setError("");
               }}
               type="button"
             >
               Create account
             </button>
           </div>
         )}


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


           {authMode !== "forgot" && (
             <>
               <label htmlFor="password">Password</label>


               <input
                 id="password"
                 type="password"
                 autoComplete={
                   authMode === "login"
                     ? "current-password"
                     : "new-password"
                 }
                 minLength={8}
                 maxLength={72}
                 required
                 value={password}
                 onChange={(e) => setPassword(e.target.value)}
                 placeholder="At least 8 characters"
               />
             </>
           )}


           <button
             className="primary-btn full-width"
             disabled={loading}
             type="submit"
           >
             {loading
               ? "Please wait..."
               : authMode === "login"
                 ? "Log in →"
                 : authMode === "register"
                   ? "Create my account →"
                   : "Send reset link →"}
           </button>
         </form>


         {authMode === "login" && (
           <button
             type="button"
             className="text-btn"
             onClick={() => {
               setAuthMode("forgot");
               setMessage("");
               setError("");
             }}
           >
             Forgot password?
           </button>
         )}


         {authMode === "forgot" && (
           <button
             type="button"
             className="text-btn"
             onClick={() => {
               setAuthMode("login");
               setMessage("");
               setError("");
             }}
           >
             Back to login
           </button>
         )}


         {message && <p className="notice">{message}</p>}
         {error && <p className="error">{error}</p>}


         <p className="small muted">
           Private history · Personal analytics
         </p>
       </section>
     </main>
   );
 }


 // TRANSLATOR DASHBOARD
 return (
   <main className="app-shell">
     <header className="topbar">
       <a className="brand" href="#translate" aria-label="Lingua home">
         <span className="brand-mark small-mark">文</span>
         <span>
           lingua<span className="brand-dot">.</span>
         </span>
       </a>


       <nav className="top-nav">
         <a href="#translate">Translate</a>
         <a href="#history">History</a>
         <a href="#analytics">Insights</a>
       </nav>


       <div className="account">
         <span className="avatar">
           {email.charAt(0).toUpperCase()}
         </span>
         <span className="account-email">{email}</span>
         <button
           className="secondary-btn"
           onClick={logout}
           type="button"
         >
           Log out
         </button>
       </div>
     </header>


     <section className="hero">
       <div>
         <p className="eyebrow">
           A LITTLE CLOSER, IN EVERY LANGUAGE
         </p>
         <h1>Say it your way.</h1>
         <p className="muted">
           Thoughtful translations. Your words, always within reach.
         </p>
       </div>


       <div className="hero-decoration" aria-hidden="true">
         <span>こんにちは</span>
         <span>నమస్కారం</span>
         <span>नमस्ते</span>
       </div>
     </section>


     {message && <p className="notice">{message}</p>}
     {error && <p className="error">{error}</p>}


     <section id="translate" className="translator-card">
       <div className="language-bar">
         <label className="language-select">
           <span>FROM</span>
           <select
             value={source}
             onChange={(e) => setSource(e.target.value)}
           >
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
           <select
             value={target}
             onChange={(e) => setTarget(e.target.value)}
           >
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
             <button
               className="text-btn"
               type="button"
               onClick={() => setInput("")}
             >
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
               type="button"
               disabled={!output}
               onClick={() => {
                 void navigator.clipboard.writeText(output).then(
                   () => {
                     setError("");
                     setMessage("Translation copied.");
                   },
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
           type="button"
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


     <section className="content-card registrations-card" id="registrations">
       <div className="section-heading">
         <div>
           <p className="eyebrow">ADMINISTRATION</p>
           <h2>Registered users</h2>
           <p className="muted">
             Registration totals and recent accounts. This information is
             available only if your account is authorized by the backend.
           </p>
         </div>
         <button
           className="secondary-btn"
           type="button"
           onClick={() => void loadRegistrations()}
           disabled={!token}
         >
           Load registrations
         </button>
       </div>

       {adminError && <p className="error">{adminError}</p>}

       {registrationStats && (
         <>
           <div className="stat-card">
             <span className="stat-icon">♙</span>
             <p>Total registered users</p>
             <strong>{registrationStats.total_registered_users}</strong>
           </div>

           <div className="activity-block">
             <h3>Registrations by day</h3>
             {registrationStats.registrations_by_day.length === 0 ? (
               <p className="empty-state">No registration activity yet.</p>
             ) : (
               registrationStats.registrations_by_day.map((day) => (
                 <div className="activity-row" key={day.date}>
                   <span>{day.date}</span>
                   <span>{day.count} registrations</span>
                 </div>
               ))
             )}
           </div>

           <div className="activity-block">
             <h3>Recent users</h3>
             {registrationStats.recent_users.length === 0 ? (
               <p className="empty-state">No users found.</p>
             ) : (
               <div className="history-list">
                 {registrationStats.recent_users.map((user) => (
                   <article className="history-item" key={user.id}>
                     <p>{user.email}</p>
                     <span className="small muted">
                       Registered: {new Date(user.registered_at).toLocaleString()}
                     </span>
                   </article>
                 ))}
               </div>
             )}
           </div>
         </>
       )}
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
             type="button"
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
                   <span>
                     {new Date(item.created_at).toLocaleString()}
                   </span>
                 </div>


                 <p>{item.source_text}</p>
                 <p className="history-result">{item.translated_text}</p>


                 <button
                   className="text-btn delete-btn"
                   onClick={() => void deleteTranslation(item.id)}
                   type="button"
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
           <p className="empty-state">
             Your language insights will grow here.
           </p>
         ) : (
           <div className="pair-list">
             {analytics.language_pairs.map((pair) => {
               const max = Math.max(
                 ...analytics.language_pairs.map((p) => p.count),
                 1,
               );


               return (
                 <div
                   className="pair-item"
                   key={`${pair.source}-${pair.target}`}
                 >
                   <div className="pair-label">
                     <span>
                       {pair.source} → {pair.target}
                     </span>
                     <strong>{pair.count}</strong>
                   </div>


                   <div className="bar-track">
                     <div
                       className="bar-fill"
                       style={{
                         width: `${(pair.count / max) * 100}%`,
                       }}
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
