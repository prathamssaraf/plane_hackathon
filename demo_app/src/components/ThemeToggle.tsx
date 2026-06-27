import React from 'react';
import { useTheme } from '../context/ThemeContext';

const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme } = useTheme();

  return (
    <button
      onClick={toggleTheme}
      style={{
        cursor: 'pointer',
        padding: '8px',
        borderRadius: '50%',
        border: '1px solid var(--primary)',
        background: 'transparent',
        fontSize: '1.2rem',
        display: 'flex',
        alignming: 'center',
        justifyContent: 'center',
        width: '40px',
        height: '40px',
        transition: 'all 0.3s ease'
      }}
      aria-label="Toggle theme"
    >
      {theme === 'light' ? '🌙' : '☀️'}
    </button>
  );
};

export default ThemeToggle;