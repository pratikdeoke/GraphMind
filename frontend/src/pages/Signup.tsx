import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

function Blobs() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <div
        className="animate-drift absolute rounded-full opacity-25"
        style={{
          width: 480, height: 480, top: '-10%', left: '-8%',
          background: 'radial-gradient(circle, rgba(99,102,241,0.5) 0%, transparent 70%)',
          filter: 'blur(55px)',
        }}
      />
      <div
        className="animate-drift absolute rounded-full opacity-20"
        style={{
          width: 360, height: 360, bottom: '8%', right: '-6%',
          background: 'radial-gradient(circle, rgba(45,212,191,0.55) 0%, transparent 70%)',
          filter: 'blur(45px)',
          animationDelay: '3.5s',
        }}
      />
    </div>
  );
}

function LogoIcon({ size = 8 }: { size?: number }) {
  const px = size * 4;
  return (
    <div
      className="animate-pulse-glow flex-shrink-0 flex items-center justify-center rounded-xl"
      style={{
        width: px, height: px,
        background: 'linear-gradient(135deg, rgba(139,92,246,0.25), rgba(99,102,241,0.15))',
        border: '1px solid rgba(139,92,246,0.35)',
      }}
    >
      <svg
        style={{ width: px * 0.45, height: px * 0.45 }}
        fill="none" stroke="rgba(167,139,250,0.9)" strokeWidth="2.2" viewBox="0 0 24 24"
      >
        <circle cx="12" cy="12" r="3" fill="rgba(167,139,250,0.2)" />
        <path d="M12 2v3m0 14v3M2 12h3m14 0h3m-3.5-6.5-2 2m-7 7-2 2m11 0-2-2m-7-7-2-2" />
      </svg>
    </div>
  );
}

function PasswordStrength({ password }: { password: string }) {
  const score = password.length === 0 ? 0
    : password.length < 6 ? 1
      : password.length < 10 ? 2
        : /[A-Z]/.test(password) && /[0-9]/.test(password) ? 4 : 3;

  const labels = ['', 'Weak', 'Fair', 'Good', 'Strong'];
  const colors = ['', '#ef4444', '#f59e0b', '#6366f1', '#2dd4bf'];

  if (!password) return null;
  return (
    <div className="flex items-center gap-2 mt-1.5">
      <div className="flex gap-1 flex-1">
        {[1, 2, 3, 4].map(i => (
          <div
            key={i}
            className="h-1 flex-1 rounded-full transition-all duration-300"
            style={{ background: i <= score ? colors[score] : 'rgba(255,255,255,0.07)' }}
          />
        ))}
      </div>
      <span style={{ fontSize: '0.6875rem', color: colors[score], fontWeight: 600, minWidth: '3rem' }}>
        {labels[score]}
      </span>
    </div>
  );
}

const features: [string, string, string][] = [
  ['#8b5cf6', 'Persistent Memory', 'Your data lives between every session'],
  ['#2dd4bf', 'Smart Extraction', 'AI structures every message into graph nodes'],
  ['#6366f1', 'Full Explainability', 'Every answer cites its exact source nodes'],
];

export default function Signup() {
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const { signup, isLoading } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (password !== confirmPassword) { setError('Passwords do not match'); return; }
    if (password.length < 6) { setError('Password must be at least 6 characters'); return; }
    try {
      await signup(email, password, fullName);
      navigate('/chat');
    } catch (err: any) {
      setError(err.message || 'Failed to create account');
    }
  };

  return (
    <div className="min-h-screen flex" style={{ background: 'var(--bg-base)' }}>
      <div
        className="hidden lg:flex flex-col justify-between w-[46%] p-14 relative overflow-hidden"
        style={{ background: 'var(--bg-surface)', borderRight: '1px solid var(--border-subtle)' }}
      >
        <Blobs />
        <div className="relative z-10 flex items-center gap-3">
          <LogoIcon size={9} />
          <span style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)' }}>GraphMind</span>
        </div>

        <div className="relative z-10 space-y-8">
          <div className="space-y-3">
            <span style={{ fontSize: '0.7rem', fontWeight: 700, letterSpacing: '0.15em', textTransform: 'uppercase', color: 'rgba(45,212,191,0.8)' }}>
              Cognitive Finance AI
            </span>
            <h2 style={{ fontSize: '2.25rem', fontWeight: 800, lineHeight: 1.15, color: 'var(--text-primary)' }}>
              Start building your<br />
              <span style={{ background: 'linear-gradient(135deg,#8b5cf6,#2dd4bf)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                financial memory.
              </span>
            </h2>
          </div>
          <p style={{ fontSize: '0.9375rem', color: 'var(--text-secondary)', lineHeight: 1.7 }}>
            Every message you send is extracted into a structured knowledge graph, all personally yours.
          </p>
          <div className="space-y-4 pt-1">
            {features.map(([color, title, desc]) => (
              <div key={title} className="flex items-start gap-3.5">
                <div className="flex-shrink-0 mt-1" style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 8px ${color}88` }} />
                <div>
                  <p style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: '0.15rem' }}>{title}</p>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
        <p className="relative z-10" style={{ fontSize: '0.7rem', color: 'var(--text-ghost)' }}>© 2026 GraphMind</p>
      </div>

      <div className="flex-1 flex items-center justify-center p-6 relative">
        <div className="lg:hidden"><Blobs /></div>

        <div className="relative z-10 w-full max-w-[400px] space-y-6 animate-fade-up">
          <div className="flex lg:hidden items-center gap-3">
            <LogoIcon size={9} />
            <span style={{ fontSize: '0.9rem', fontWeight: 600, color: 'var(--text-primary)' }}>GraphMind</span>
          </div>

          <div>
            <h1 style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
              Create your account
            </h1>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>
              Your financial memory starts here
            </p>
          </div>

          {error && (
            <div className="animate-scale-in flex items-start gap-2.5 rounded-xl text-sm"
              style={{ padding: '0.875rem', background: 'rgba(239,68,68,0.07)', border: '1px solid rgba(239,68,68,0.2)', color: '#f87171' }}>
              <svg className="flex-shrink-0 mt-0.5" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label style={{ fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Full Name</label>
              <input type="text" value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Tanmay Sharma" required disabled={isLoading} className="input-field" />
            </div>
            <div className="space-y-1.5">
              <label style={{ fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" required disabled={isLoading} className="input-field" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label style={{ fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Password</label>
                <div className="relative">
                  <input type={showPw ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="••••••••" required disabled={isLoading}
                    className="input-field" style={{ paddingRight: '2.5rem' }} />
                  <button type="button" onClick={() => setShowPw(v => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2"
                    style={{ color: 'var(--text-muted)', background: 'none', border: 'none', cursor: 'pointer' }}>
                    <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                      {showPw
                        ? <><path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94" /><path d="M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19" /><line x1="1" y1="1" x2="23" y2="23" /></>
                        : <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>
                      }
                    </svg>
                  </button>
                </div>
                <PasswordStrength password={password} />
              </div>
              <div className="space-y-1.5">
                <label style={{ fontSize: '0.6875rem', fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>Confirm</label>
                <input type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)}
                  placeholder="••••••••" required disabled={isLoading} className="input-field" />
                {confirmPassword && password !== confirmPassword && (
                  <p style={{ fontSize: '0.7rem', color: '#ef4444', marginTop: '0.25rem' }}>Passwords don't match</p>
                )}
              </div>
            </div>

            <button type="submit" disabled={isLoading} className="btn-primary" style={{ marginTop: '0.25rem' }}>
              {isLoading
                ? <><svg className="animate-spin" width="16" height="16" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="white" strokeWidth="4" /><path className="opacity-75" fill="white" d="M4 12a8 8 0 018-8v8H4z" /></svg> Creating account...</>
                : 'Create account'
              }
            </button>
          </form>

          <p className="text-center" style={{ fontSize: '0.8125rem', color: 'var(--text-ghost)' }}>
            Have an account?{' '}
            <Link to="/login" style={{ color: 'var(--accent-1)', fontWeight: 600 }} className="hover:opacity-80 transition-opacity">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
