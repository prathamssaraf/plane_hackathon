import React from 'react';
import { useTheme } from '../context/ThemeContext';

const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      style={{
        cursor: 'pointer',
        padding: '8px 12px',
        borderRadius: '8px',
        border: '1px solid var(--text-color)',
        background: 'transparent',
        color: 'var(--text-color)',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        transition: 'all 0.2s ease'
      }}
      aria-label="Toggle theme"
    >
      <span>{theme === 'light' ? '🌙' : '☀️'}</span>
      <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>
        {theme === 'light' ? 'Dark Mode' : 'Light Mode'}
      </span>
    </button>
  );
};

export default ThemeToggle;