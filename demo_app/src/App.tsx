import React from 'react';
import './App.css';
import { ThemeProvider } from './context/ThemeContext';
import ThemeToggle from './components/ThemeToggle';

function App() {
  return (
    <ThemeProvider>
      <div id="root">
        <header style={{ 
          display: 'flex', 
          justifyContent: 'space-between', 
          alignItems: 'center', 
          marginBottom: '2rem' 
        }}>
          <h1>Demo App</h1>
          <ThemeToggle />
        </header>
        <main>
          <p>
            Welcome to the demo application! This app supports <a href="https://react.dev" target="_blank">React</a> and dark mode.
          </p>
        </main>
      </div>
    </ThemeProvider>
  );
}

export default App;