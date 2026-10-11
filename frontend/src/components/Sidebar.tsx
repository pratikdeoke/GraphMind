import React from 'react';

interface SidebarProps {
  financialSummary: { 
    totalInvested: number;
    totalAssets: number;
    netWorth: number;
    banks: { name: string; count: number }[];
    investments: { name: string; amount: number; type: string }[];
    isEmpty: boolean;
  };
  open: boolean;
  onToggle: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ financialSummary, open, onToggle }) => {
  return (
    <>
      {/* Premium Toggle Button - Always Visible with Enhanced Design */}
      <button
        onClick={onToggle}
        style={{
          position: 'fixed',
          left: open ? 320 : 12,
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 50,
          background: open 
            ? 'linear-gradient(135deg, #8b5cf6 0%, #6366f1 100%,0.1)' 
            : 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%,0.9)',
          color: '#fff',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: open ? '0 16px 16px 0' : '0 12px 12px 0',
          boxShadow: open 
            ? '0 8px 32px rgba(139,92,246,0.4), inset 0 1px 0 rgba(255,255,255,0.1)' 
            : '0 10px 40px rgba(99,102,241,0.35), inset 0 1px 0 rgba(255,255,255,0.15)',
          width: 48,
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          cursor: 'pointer',
          transition: 'all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
          backdropFilter: 'blur(10px)',
        }}
        onMouseEnter={(e) => { 
          (e.currentTarget as HTMLButtonElement).style.boxShadow = open
            ? '0 12px 48px rgba(139,92,246,0.5), inset 0 1px 0 rgba(255,255,255,0.2)' 
            : '0 14px 56px rgba(99,102,241,0.45), inset 0 1px 0 rgba(255,255,255,0.2)';
          (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-50%) scale(1.08)';
        }}
        onMouseLeave={(e) => { 
          (e.currentTarget as HTMLButtonElement).style.boxShadow = open 
            ? '0 8px 32px rgba(139,92,246,0.4), inset 0 1px 0 rgba(255,255,255,0.1)' 
            : '0 10px 40px rgba(99,102,241,0.35), inset 0 1px 0 rgba(255,255,255,0.15)';
          (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-50%)';
        }}
        aria-label={open ? 'Hide sidebar' : 'Show sidebar'}
        title={open ? 'Close sidebar' : 'Open sidebar'}
      >
        <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" style={{ transition: 'transform 0.3s ease' }}>
          {open ? (
            <path d="M15 19l-7-7 7-7" strokeLinecap="round" strokeLinejoin="round" />
          ) : (
            <path d="M9 5l7 7-7 7" strokeLinecap="round" strokeLinejoin="round" />
          )}
        </svg>
      </button>
      {/* Sidebar */}
      <aside
        style={{
          width: open ? 320 : 0,
          minWidth: open ? 320 : 0,
          height: '100vh',
          background: 'linear-gradient(135deg,#0f0f1a 0%,#161622 100%)',
          borderRight: open ? '1.5px solid rgba(139,92,246,0.2)' : 'none',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          position: 'fixed',
          left: 0,
          top: 0,
          zIndex: 20,
          boxShadow: open ? '8px 0 48px 0 rgba(99,102,241,0.12)' : 'none',
          overflow: 'hidden',
          transition: 'width 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.3s ease',
        }}
      >
        {/* Financial Summary Section */}
        <div style={{ padding: open ? '1.8rem 1.4rem 1.2rem 1.4rem' : 0, borderBottom: open ? '1px solid rgba(139,92,246,0.12)' : 'none', opacity: open ? 1 : 0, transition: 'opacity 0.3s', overflowY: 'auto', maxHeight: open ? '55%' : 0 }}>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800, background: 'linear-gradient(135deg,#c4b5fd,#818cf8)', backgroundClip: 'text', WebkitBackgroundClip: 'text', color: 'transparent', marginBottom: 14, letterSpacing: 0.4 }}>💰 Financial Overview</h2>
          
          {financialSummary.isEmpty ? (
            <div style={{ padding: '1.2rem 0.8rem', background: 'linear-gradient(135deg, rgba(139,92,246,0.08), rgba(99,102,241,0.05))', borderRadius: 12, border: '1px dashed rgba(139,92,246,0.2)', textAlign: 'center' }}>
              <div style={{ fontSize: '2.2rem', marginBottom: 8 }}>📝</div>
              <p style={{ fontSize: '0.85rem', color: '#a0a0b0', margin: 0, lineHeight: 1.5 }}>Start adding your financial data to see summaries here</p>
            </div>
          ) : (
            <>
              {/* Key Metrics */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
                <div style={{ padding: '0.9rem', background: 'linear-gradient(135deg, rgba(139,92,246,0.15), rgba(139,92,246,0.05))', borderRadius: 10, border: '1px solid rgba(139,92,246,0.15)' }}>
                  <div style={{ fontSize: '0.75rem', color: '#9090a0', fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>Invested</div>
                  <div style={{ color: '#a78bfa', fontWeight: 800, fontSize: '1rem' }}>₹{financialSummary.totalInvested.toLocaleString()}</div>
                </div>
                <div style={{ padding: '0.9rem', background: 'linear-gradient(135deg, rgba(16,185,129,0.15), rgba(16,185,129,0.05))', borderRadius: 10, border: '1px solid rgba(16,185,129,0.15)' }}>
                  <div style={{ fontSize: '0.75rem', color: '#9090a0', fontWeight: 600, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>Net Worth</div>
                  <div style={{ color: '#6ee7b7', fontWeight: 800, fontSize: '1rem' }}>₹{financialSummary.netWorth.toLocaleString()}</div>
                </div>
              </div>

              {/* Banks Section */}
              <div style={{ marginBottom: 14 }}>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: '#d0d0d8', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>🏦 Banks {financialSummary.banks.length > 0 && <span style={{ fontSize: '0.8rem', color: '#8b8b98' }}>({financialSummary.banks.length})</span>}</h3>
                {financialSummary.banks.length === 0 ? (
                  <p style={{ fontSize: '0.8rem', color: '#8080a0', marginBottom: 0 }}>No banks added yet</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {financialSummary.banks.map((bank, idx) => (
                      <div key={idx} style={{ padding: '0.6rem 0.8rem', background: 'rgba(139,92,246,0.08)', borderRadius: 8, border: '1px solid rgba(139,92,246,0.1)', fontSize: '0.85rem', color: '#c4b5fd' }}>
                        {bank.name}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Investments Section */}
              <div>
                <h3 style={{ fontSize: '0.9rem', fontWeight: 700, color: '#d0d0d8', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}>📈 Investments {financialSummary.investments.length > 0 && <span style={{ fontSize: '0.8rem', color: '#8b8b98' }}>({financialSummary.investments.length})</span>}</h3>
                {financialSummary.investments.length === 0 ? (
                  <p style={{ fontSize: '0.8rem', color: '#8080a0', marginBottom: 0 }}>No investments recorded yet</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {financialSummary.investments.slice(0, 4).map((inv, idx) => (
                      <div key={idx} style={{ padding: '0.6rem 0.8rem', background: 'rgba(16,185,129,0.08)', borderRadius: 8, border: '1px solid rgba(16,185,129,0.1)', fontSize: '0.8rem' }}>
                        <div style={{ color: '#6ee7b7', fontWeight: 700 }}>{inv.name}</div>
                        <div style={{ color: '#80b8a0', fontSize: '0.75rem', marginTop: 4 }}>₹{inv.amount.toLocaleString()} • {inv.type}</div>
                      </div>
                    ))}
                    {financialSummary.investments.length > 4 && (
                      <div style={{ fontSize: '0.8rem', color: '#8080a0', marginTop: 6 }}>+ {financialSummary.investments.length - 4} more investments</div>
                    )}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
