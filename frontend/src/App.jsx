import React, { createContext, useContext, useState } from 'react';

// Theme Context
const ThemeContext = createContext();
const ThemeProvider = ({ children }) => {
  const [theme, setTheme] = useState('dark');
  const toggleTheme = () => setTheme(p => p === 'dark' ? 'light' : 'dark');
  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>;
};
const useTheme = () => useContext(ThemeContext);

// Auth Context
const AuthContext = createContext();
const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [page, setPage] = useState('home');
  const login = (email) => { setUser({ name: 'John Doe', email }); setPage('dashboard'); };
  const logout = () => { setUser(null); setPage('home'); };
  return <AuthContext.Provider value={{ user, login, logout, page, setPage }}>{children}</AuthContext.Provider>;
};
const useAuth = () => useContext(AuthContext);

// Wallet Context
const WalletContext = createContext();
const WalletProvider = ({ children }) => {
  const [balance, setBalance] = useState(100);
  const [txns, setTxns] = useState([
    { id: 1, type: 'credit', amt: 100, desc: 'Welcome bonus', date: '2025-01-01' },
    { id: 2, type: 'debit', amt: 10, desc: 'Template purchase', date: '2025-01-02' }
  ]);
  const addFunds = (amt) => {
    setBalance(p => p + amt);
    setTxns(p => [{ id: Date.now(), type: 'credit', amt, desc: 'Funds added', date: new Date().toISOString().split('T')[0] }, ...p]);
  };
  const deduct = (amt, desc) => {
    if (balance >= amt) {
      setBalance(p => p - amt);
      setTxns(p => [{ id: Date.now(), type: 'debit', amt, desc, date: new Date().toISOString().split('T')[0] }, ...p]);
      return true;
    }
    return false;
  };
  return <WalletContext.Provider value={{ balance, txns, addFunds, deduct }}>{children}</WalletContext.Provider>;
};
const useWallet = () => useContext(WalletContext);

// Navbar
const Nav = () => {
  const { theme, toggleTheme } = useTheme();
  const { user, logout, setPage } = useAuth();
  const { balance } = useWallet();
  return (
    <nav className={`nav ${theme}`}>
      <div className="nav-wrap">
        <div onClick={() => setPage('home')} className="logo">
          <div className="logo-i">B</div>
          <span className="logo-t">BannerHub</span>
        </div>
        <div className="menu">
          <a onClick={() => setPage('home')}>Home</a>
          <a onClick={() => setPage('templates')}>Templates</a>
          {user && <>
            <a onClick={() => setPage('dashboard')}>Dashboard</a>
            <div className="wallet-b">💳 ${balance}</div>
          </>}
        </div>
        <div className="acts">
          <button onClick={toggleTheme} className="theme-b">{theme === 'dark' ? '☀️' : '🌙'}</button>
          {user ? <button onClick={logout} className="btn-sec">Logout</button> : <button onClick={() => setPage('login')} className="btn-pri">Get Started</button>}
        </div>
      </div>
    </nav>
  );
};

// Home Page
const Home = () => {
  const { setPage } = useAuth();
  return (
    <div className="pg">
      <section className="hero">
        <div className="hero-bg">
          <div className="orb orb1"></div>
          <div className="orb orb2"></div>
          <div className="orb orb3"></div>
        </div>
        <div className="hero-c">
          <div className="badge">✨ AI-Powered Banner Generation</div>
          <h1 className="h-title">Create Stunning Banners<br/><span className="grad">In Seconds</span></h1>
          <p className="h-sub">Professional banner designs powered by AI. No design skills needed.</p>
          <div className="h-acts">
            <button onClick={() => setPage('login')} className="btn-pri btn-lg">Start Creating Free →</button>
            <button onClick={() => setPage('templates')} className="btn-gho btn-lg">View Templates</button>
          </div>
          <div className="stats">
            {[['50K+', 'Banners Created'], ['10K+', 'Active Users'], ['500+', 'Templates']].map(([v, l], i) => (
              <div key={i} className="stat">
                <div className="stat-v grad">{v}</div>
                <div className="stat-l">{l}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="feat">
        <h2 className="sec-h">Powerful Features for <span className="grad">Everyone</span></h2>
        <div className="feat-g">
          {[
            ['🎨', 'AI Design', 'Generate professional banners'],
            ['⚡', 'Lightning Fast', 'Create in seconds'],
            ['🎯', 'Smart Templates', '500+ templates'],
            ['💎', 'Premium Quality', 'High-resolution exports'],
            ['🔧', 'Full Custom', 'Edit every aspect'],
            ['💳', 'Credit System', 'Pay what you use']
          ].map(([ic, t, d], i) => (
            <div key={i} className="f-card">
              <div className="f-ic">{ic}</div>
              <h3>{t}</h3>
              <p>{d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="cta">
        <div className="cta-c">
          <h2>Ready to Create Amazing Banners?</h2>
          <p>Join thousands of creators</p>
          <button onClick={() => setPage('login')} className="btn-pri btn-lg">Get Started Now</button>
        </div>
      </section>

      <footer className="foot">
        <div className="foot-c">
          <div className="logo"><div className="logo-i">B</div><span className="logo-t">BannerHub</span></div>
          <p>© 2025 BannerHub. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
};

// Login Page
const Login = () => {
  const { login, setPage } = useAuth();
  const [email, setEmail] = useState('');
  return (
    <div className="pg auth-pg">
      <div className="auth-c">
        <h2>Welcome Back</h2>
        <p className="auth-sub">Sign in to BannerHub</p>
        <form onSubmit={(e) => { e.preventDefault(); login(email); }} className="auth-f">
          <div className="fg">
            <label>Email</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required />
          </div>
          <div className="fg">
            <label>Password</label>
            <input type="password" placeholder="••••••••" required />
          </div>
          <button type="submit" className="btn-pri btn-full">Sign In</button>
        </form>
      </div>
    </div>
  );
};

// Dashboard
const Dashboard = () => {
  const { balance, txns } = useWallet();
  const { setPage } = useAuth();
  return (
    <div className="pg dash-pg">
      <div className="cont">
        <h1 className="pg-title">Dashboard</h1>
        <div className="dash-g">
          <div className="card w-card">
            <h3>Wallet Balance</h3>
            <div className="w-bal">${balance}</div>
            <button onClick={() => setPage('wallet')} className="btn-pri">Add Funds</button>
          </div>
          <div className="card">
            <h3>Quick Stats</h3>
            <div className="stat-r"><span>Banners Created</span><strong>12</strong></div>
            <div className="stat-r"><span>Credits Used</span><strong>45</strong></div>
          </div>
        </div>
        <div className="card txn-card">
          <h3>Recent Transactions</h3>
          {txns.slice(0, 5).map(t => (
            <div key={t.id} className="txn">
              <div className="txn-i">
                <span className={`txn-ic ${t.type}`}>{t.type === 'credit' ? '💵' : '💳'}</span>
                <div>
                  <div className="txn-d">{t.desc}</div>
                  <div className="txn-dt">{t.date}</div>
                </div>
              </div>
              <div className={`txn-a ${t.type}`}>{t.type === 'credit' ? '+' : '-'}${t.amt}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// Templates
const Templates = () => {
  const { deduct } = useWallet();
  const { setPage } = useAuth();
  const temps = [
    { id: 1, name: 'E-commerce Sale', price: 0, grad: 'linear-gradient(135deg, #ef4444, #f97316)' },
    { id: 2, name: 'Tech Launch', price: 5, grad: 'linear-gradient(135deg, #3b82f6, #06b6d4)' },
    { id: 3, name: 'Fashion Brand', price: 5, grad: 'linear-gradient(135deg, #ec4899, #a855f7)' },
    { id: 4, name: 'Food & Restaurant', price: 0, grad: 'linear-gradient(135deg, #eab308, #f97316)' },
    { id: 5, name: 'Real Estate', price: 10, grad: 'linear-gradient(135deg, #10b981, #14b8a6)' },
    { id: 6, name: 'Fitness & Health', price: 10, grad: 'linear-gradient(135deg, #a855f7, #6366f1)' }
  ];
  return (
    <div className="pg temp-pg">
      <div className="cont">
        <h1 className="pg-title">Browse Templates</h1>
        <div className="temp-g">
          {temps.map(t => (
            <div key={t.id} className="temp-card">
              <div className="temp-prev" style={{ background: t.grad }}>🎨</div>
              <div className="temp-inf">
                <h3>{t.name}</h3>
                <div className="temp-foot">
                  <span className={t.price === 0 ? 'free' : 'paid'}>{t.price === 0 ? 'Free' : `$${t.price}`}</span>
                  <button onClick={() => {
                    if (t.price === 0 || deduct(t.price, `Template: ${t.name}`)) setPage('editor');
                    else alert('Insufficient balance!');
                  }} className="btn-pri btn-sm">Use</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// Editor
const Editor = () => {
  const { deduct } = useWallet();
  const [prompt, setPrompt] = useState('');
  const [gen, setGen] = useState(false);
  return (
    <div className="pg ed-pg">
      <div className="ed-wrap">
        <div className="card ed-side">
          <h3>Banner Settings</h3>
          <div className="fg">
            <label>Description</label>
            <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe your banner..." rows="4" />
          </div>
          <div className="fg">
            <label>Size</label>
            <select><option>1200x628</option><option>728x90</option><option>300x250</option></select>
          </div>
          <button disabled={gen} onClick={() => {
            if (deduct(5, 'Banner generation')) { setGen(true); setTimeout(() => { setGen(false); alert('Generated!'); }, 2000); }
            else alert('Insufficient balance!');
          }} className="btn-pri btn-full">{gen ? 'Generating...' : 'Generate ($5)'}</button>
        </div>
        <div className="card ed-canv">
          {gen ? <div className="load">🎨</div> : <><span className="canv-ic">🖼️</span><p>Your banner will appear here</p></>}
        </div>
      </div>
    </div>
  );
};

// Wallet
const Wallet = () => {
  const { balance, txns, addFunds } = useWallet();
  const [amt, setAmt] = useState('');
  return (
    <div className="pg wal-pg">
      <div className="cont">
        <h1 className="pg-title">Wallet</h1>
        <div className="card w-bal-card">
          <h3>Current Balance</h3>
          <div className="bal-disp">${balance}</div>
        </div>
        <div className="card">
          <h3>Add Funds</h3>
          <div className="preset">
            {[10, 25, 50, 100].map(a => <button key={a} onClick={() => { addFunds(a); alert(`$${a} added!`); }} className="amt-btn">${a}</button>)}
          </div>
          <div className="custom">
            <input type="number" value={amt} onChange={(e) => setAmt(e.target.value)} placeholder="Custom amount" />
            <button onClick={() => { if (amt > 0) { addFunds(Number(amt)); setAmt(''); alert('Added!'); } }} className="btn-pri">Add</button>
          </div>
        </div>
        <div className="card">
          <h3>Transaction History</h3>
          {txns.map(t => (
            <div key={t.id} className="txn">
              <div className="txn-i">
                <span className={`txn-ic ${t.type}`}>{t.type === 'credit' ? '💵' : '💳'}</span>
                <div><div className="txn-d">{t.desc}</div><div className="txn-dt">{t.date}</div></div>
              </div>
              <div className={`txn-a ${t.type}`}>{t.type === 'credit' ? '+' : '-'}${t.amt}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// App
export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <WalletProvider>
          <Main />
        </WalletProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

const Main = () => {
  const { page } = useAuth();
  const { theme } = useTheme();
  return (
    <div className={`app ${theme}`}>
      <style>{`
        *{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,sans-serif;overflow-x:hidden}.app{min-height:100vh;background:#0a0a0f;color:#fff;transition:all .3s}.app.light{background:#fff;color:#0a0a0f}.nav{position:fixed;top:0;left:0;right:0;z-index:1000;background:rgba(10,10,15,.85);backdrop-filter:blur(40px);border-bottom:1px solid rgba(255,255,255,.1)}.nav.light{background:rgba(255,255,255,.85);border-bottom:1px solid rgba(0,0,0,.1)}.nav-wrap{max-width:1280px;margin:0 auto;padding:0 1rem;display:flex;align-items:center;justify-content:space-between;height:80px}.logo{display:flex;align-items:center;gap:.5rem;cursor:pointer}.logo-i{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#6366f1,#8b5cf6);display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:1.25rem}.logo-t{font-size:1.5rem;font-weight:700;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.menu{display:flex;align-items:center;gap:2rem}.menu a{color:#a0a0b0;cursor:pointer;transition:color .3s;font-weight:500}.menu a:hover{color:#fff}.light .menu a:hover{color:#0a0a0f}.wallet-b{display:flex;align-items:center;gap:.5rem;padding:.5rem 1rem;border-radius:10px;background:linear-gradient(135deg,rgba(99,102,241,.1),rgba(139,92,246,.1));border:1px solid rgba(99,102,241,.3);font-weight:600;color:#8b5cf6}.acts{display:flex;align-items:center;gap:1rem}.theme-b{width:40px;height:40px;border-radius:10px;border:1px solid rgba(255,255,255,.1);background:0 0;cursor:pointer;font-size:1.25rem;transition:all .3s}.theme-b:hover{background:rgba(99,102,241,.1);border-color:#6366f1}.btn-pri{background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;padding:.75rem 2rem;border-radius:12px;font-weight:600;border:none;cursor:pointer;transition:all .3s;box-shadow:0 4px 20px rgba(99,102,241,.3)}.btn-pri:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(99,102,241,.4)}.btn-pri:disabled{opacity:.5;cursor:not-allowed}.btn-sec{background:0 0;color:currentColor;padding:.625rem 1.5rem;border-radius:10px;font-weight:500;border:1px solid rgba(255,255,255,.1);cursor:pointer;transition:all .3s}.btn-gho{background:0 0;border:1px solid rgba(255,255,255,.1);color:currentColor;padding:.75rem 2rem;border-radius:12px;font-weight:600;cursor:pointer;transition:all .3s}.btn-gho:hover{border-color:#6366f1;background:rgba(99,102,241,.1)}.btn-lg{padding:1rem 2.5rem;font-size:1.125rem}.btn-sm{padding:.5rem 1rem;font-size:.875rem}.btn-full{width:100%}.pg{min-height:100vh;padding-top:80px}.hero{position:relative;min-height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden}.hero-bg{position:absolute;inset:0}.orb{position:absolute;border-radius:50%;filter:blur(80px);animation:float 8s infinite}.orb1{width:400px;height:400px;background:radial-gradient(circle,rgba(99,102,241,.15),transparent);top:10%;left:10%}.orb2{width:500px;height:500px;background:radial-gradient(circle,rgba(139,92,246,.15),transparent);bottom:10%;right:10%;animation-delay:-2s}.orb3{width:300px;height:300px;background:radial-gradient(circle,rgba(240,147,251,.1),transparent);top:50%;left:50%;animation-delay:-4s}@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-30px)}}.hero-c{position:relative;z-index:10;text-align:center;max-width:1280px;padding:0 2rem}.badge{display:inline-block;padding:.5rem 1.5rem;border-radius:50px;background:linear-gradient(135deg,rgba(99,102,241,.1),rgba(139,92,246,.1));border:1px solid rgba(255,255,255,.1);font-size:.875rem;font-weight:500;margin-bottom:2rem}.h-title{font-size:clamp(2.5rem,8vw,4.5rem);font-weight:800;line-height:1.2;margin-bottom:1.5rem}.grad{background:linear-gradient(135deg,#6366f1,#8b5cf6,#f093fb);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.h-sub{font-size:1.25rem;color:#a0a0b0;max-width:48rem;margin:0 auto 3rem;line-height:1.6}.h-acts{display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin-bottom:5rem}.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:2rem;max-width:48rem;margin:0 auto}.stat{text-align:center}.stat-v{font-size:2rem;font-weight:700;margin-bottom:.5rem}.stat-l{font-size:.875rem;color:#6b6b7f}.feat{padding:8rem 2rem;text-align:center}.sec-h{font-size:clamp(2rem,5vw,3rem);font-weight:700;margin-bottom:1rem}.feat-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:2rem;max-width:1280px;margin:3rem auto 0}.f-card{background:rgba(19,19,26,.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:2rem;transition:all .3s;position:relative}.f-card:hover{transform:translateY(-8px);border-color:#6366f1}.f-ic{font-size:3rem;margin-bottom:1rem}.f-card h3{font-size:1.25rem;margin-bottom:.5rem}.f-card p{color:#a0a0b0}.cta{padding:8rem 2rem}.cta-c{max-width:800px;margin:0 auto;background:rgba(13,13,18,.8);backdrop-filter:blur(30px);border:1px solid rgba(255,255,255,.1);border-radius:24px;padding:4rem 2rem;text-align:center}.cta-c h2{font-size:2.5rem;margin-bottom:1rem}.cta-c p{color:#a0a0b0;margin-bottom:2rem}.foot{border-top:1px solid rgba(255,255,255,.1);padding:3rem 2rem}.foot-c{max-width:1280px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:2rem}.foot-c p{color:#6b6b7f}.auth-pg{display:flex;align-items:center;justify-content:center;min-height:calc(100vh - 80px);padding:2rem}.auth-c{width:100%;max-width:400px;background:rgba(19,19,26,.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:2rem}.auth-c h2{font-size:2rem;margin-bottom:.5rem}.auth-sub{color:#a0a0b0;margin-bottom:2rem}.auth-f{display:flex;flex-direction:column;gap:1.5rem}.fg{display:flex;flex-direction:column;gap:.5rem}.fg label{font-size:.875rem;font-weight:500;color:#a0a0b0}.fg input,.fg select,.fg textarea{background:rgba(26,26,36,.6);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:.75rem 1rem;color:#fff;font-size:1rem;transition:all .3s;width:100%}.fg input:focus,.fg select:focus,.fg textarea:focus{outline:0;border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.1)}.dash-pg,.temp-pg,.wal-pg{padding:2rem}.cont{max-width:1280px;margin:0 auto}.pg-title{font-size:2.5rem;font-weight:700;margin-bottom:2rem}.dash-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:2rem;margin-bottom:2rem}.card{background:rgba(19,19,26,.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:20px;padding:2rem;transition:all .3s}.card h3{font-size:1.5rem;margin-bottom:1.5rem}.w-card{text-align:center}.w-bal{font-size:3rem;font-weight:700;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin-bottom:1.5rem}.stat-r{display:flex;justify-content:space-between;padding:.75rem 0;border-bottom:1px solid rgba(255,255,255,.05)}.stat-r:last-child{border:0}.txn-card .txn:not(:last-child){margin-bottom:1rem}.txn{display:flex;justify-content:space-between;align-items:center;padding:1rem;background:rgba(26,26,36,.4);border-radius:12px}.txn-i{display:flex;align-items:center;gap:1rem}.txn-ic{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.25rem}.txn-ic.credit{background:rgba(16,185,129,.1)}.txn-ic.debit{background:rgba(139,92,246,.1)}.txn-d{font-weight:500;margin-bottom:.25rem}.txn-dt{font-size:.75rem;color:#6b6b7f}.txn-a{font-weight:600;font-size:1.125rem}.txn-a.credit{color:#10b981}.txn-a.debit{color:#8b5cf6}.temp-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:2rem}.temp-card{background:rgba(19,19,26,.6);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.1);border-radius:20px;overflow:hidden;transition:all .3s;cursor:pointer}.temp-card:hover{transform:scale(1.05)}.temp-prev{aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;font-size:4rem}.temp-inf{padding:1.5rem}.temp-inf h3{margin-bottom:1rem}.temp-foot{display:flex;justify-content:space-between;align-items:center}.temp-foot .free{background:rgba(16,185,129,.1);color:#10b981;padding:.25rem .75rem;border-radius:6px;font-size:.875rem;font-weight:600}.temp-foot .paid{background:rgba(139,92,246,.1);color:#8b5cf6;padding:.25rem .75rem;border-radius:6px;font-size:.875rem;font-weight:600}.ed-pg{padding:2rem}.ed-wrap{display:grid;grid-template-columns:350px 1fr;gap:2rem;max-width:1400px;margin:0 auto}.ed-side{height:fit-content}.ed-canv{min-height:500px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:rgba(26,26,36,.4)}.canv-ic{font-size:4rem;margin-bottom:1rem}.load{font-size:4rem;animation:spin 2s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.w-bal-card{text-align:center}.bal-disp{font-size:4rem;font-weight:700;background:linear-gradient(135deg,#6366f1,#8b5cf6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}.preset{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:1.5rem}.amt-btn{background:rgba(99,102,241,.1);border:1px solid rgba(99,102,241,.3);color:#8b5cf6;padding:1rem;border-radius:12px;font-weight:600;cursor:pointer;transition:all .3s}.amt-btn:hover{background:rgba(99,102,241,.2);transform:scale(1.05)}.custom{display:flex;gap:1rem}.custom input{flex:1}@media(max-width:768px){.menu{display:none}.nav-wrap{padding:0 1rem}.stats{grid-template-columns:1fr}.feat-g{grid-template-columns:1fr}.dash-g{grid-template-columns:1fr}.temp-g{grid-template-columns:1fr}.ed-wrap{grid-template-columns:1fr}.preset{grid-template-columns:repeat(2,1fr)}}
      `}</style>
      <Nav />
      {page === 'home' && <Home />}
      {page === 'login' && <Login />}
      {page === 'dashboard' && <Dashboard />}
      {page === 'templates' && <Templates />}
      {page === 'editor' && <Editor />}
      {page === 'wallet' && <Wallet />}
    </div>
  );
};
