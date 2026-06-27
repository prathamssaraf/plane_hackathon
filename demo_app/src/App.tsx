import React from 'react';
import './App.css';
import { ThemeProvider } from './context/ThemeContext';
import ThemeToggle from './components/ThemeToggle';
import CanvasDiff from './components/CanvasDiff';

function App() {
  return (
    <ThemeProvider>
      <div className="app-container">
        <header>
          <h1>Demo App</h1>
          <ThemeToggle />
        </header>
        <main>
          <section className="card">
            <h2>Code Comparison</h2>
            <p>Explore the differences between versions using our interactive canvas.</p>
            <CanvasDiff />
          </section>
        </main>
      </div>
    </ThemeProvider>
  );
}

export default App;