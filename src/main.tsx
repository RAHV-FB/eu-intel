import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { preloadRouteData } from './lib/routeData';
import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/layout.css';

// the data of the page opened, requested now rather than once its code has loaded and it has rendered
const base = import.meta.env.BASE_URL.replace(/\/$/, '');
const path = window.location.pathname;
if (path === base || path.startsWith(`${base}/`)) preloadRouteData(path.slice(base.length), window.location.search);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
