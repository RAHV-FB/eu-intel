import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Loading, NotFound } from './components/ui';

/**
 * Routes. Pages are lazy-loaded so the homepage stays small.
 * GitHub Pages: scripts/prerender-routes.mjs writes an index.html for every known route
 * (so direct navigation returns 200) plus a 404.html SPA fallback.
 */
const Home = lazy(() => import('./pages/Home'));
const Legislation = lazy(() => import('./pages/Legislation'));
const Dossier = lazy(() => import('./pages/Dossier'));
const Search = lazy(() => import('./pages/Search'));
const Following = lazy(() => import('./pages/Following'));
const Votes = lazy(() => import('./pages/Votes'));
const Vote = lazy(() => import('./pages/Vote'));
const People = lazy(() => import('./pages/People'));
const Mep = lazy(() => import('./pages/Mep'));
const Group = lazy(() => import('./pages/Group'));
const Party = lazy(() => import('./pages/Party'));
const Countries = lazy(() => import('./pages/Countries'));
const Country = lazy(() => import('./pages/Country'));
const HowEuWorks = lazy(() => import('./pages/HowEuWorks'));
const About = lazy(() => import('./pages/About'));
const Privacy = lazy(() => import('./pages/Privacy'));

function TopicRedirect() {
  const { slug } = useParams();
  return <Navigate to={`/legislation?topic=${encodeURIComponent(slug ?? '')}`} replace />;
}

export function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, '') || '/'}>
      <Suspense fallback={<div className="container page"><Loading /></div>}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="legislation" element={<Legislation />} />
            <Route path="legislation/:id" element={<Dossier />} />
            <Route path="topics/:slug" element={<TopicRedirect />} />
            <Route path="search" element={<Search />} />
            <Route path="following" element={<Following />} />
            <Route path="votes" element={<Votes />} />
            <Route path="votes/:id" element={<Vote />} />
            <Route path="people" element={<People />} />
            <Route path="people/meps/:id" element={<Mep />} />
            <Route path="people/groups/:id" element={<Group />} />
            <Route path="people/parties/:id" element={<Party />} />
            <Route path="countries" element={<Countries />} />
            <Route path="countries/:code" element={<Country />} />
            <Route path="how-the-eu-works" element={<HowEuWorks />} />
            <Route path="about" element={<About />} />
            <Route path="privacy" element={<Privacy />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
