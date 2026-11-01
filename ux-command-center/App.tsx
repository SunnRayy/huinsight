import React, { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { useAuth } from './src/context/useAuth';
import { LoginPage } from './pages/LoginPage';
import { DemoModeProvider } from './src/context/useDemoMode';
import { CurrencyProvider } from './src/context/useCurrency';
import { LanguageProvider } from './src/context/useLanguage';
import { Dashboard } from './pages/Dashboard';

// Route-level code splitting (cloud-speed plan, phase 3): each page below is
// its own chunk, fetched when first visited. Dashboard and Login stay in the
// main bundle because one of them is always the first screen.
const page = <T extends string>(load: () => Promise<Record<T, React.ComponentType>>, name: T) =>
  lazy(() => load().then((m) => ({ default: m[name] })));
const RiskMatrix = page(() => import('./pages/RiskMatrix'), 'RiskMatrix');
const Performance = page(() => import('./pages/Performance'), 'Performance');
const WealthOS = page(() => import('./pages/WealthOS'), 'WealthOS');
const Compass = page(() => import('./pages/Compass'), 'Compass');
const Audit = page(() => import('./pages/Audit'), 'Audit');
const Verification = page(() => import('./pages/Verification'), 'Verification');
const DecisionHub = page(() => import('./pages/DecisionHub'), 'DecisionHub');
const Taxonomy = page(() => import('./pages/Taxonomy'), 'Taxonomy');
const RiskProfiles = page(() => import('./pages/RiskProfiles'), 'RiskProfiles');
const TransactionBrowser = page(() => import('./pages/TransactionBrowser'), 'TransactionBrowser');
const ImportWorkbench = page(() => import('./pages/ImportWorkbench'), 'ImportWorkbench');
const AssetAudit = page(() => import('./pages/AssetAudit'), 'AssetAudit');
const AssetClassAudit = page(() => import('./pages/AssetClassAudit'), 'AssetClassAudit');
const AssetCaseFile = page(() => import('./pages/AssetCaseFile'), 'AssetCaseFile');
const TierAudit = page(() => import('./pages/TierAudit'), 'TierAudit');
const ClassificationRules = page(() => import('./pages/ClassificationRules'), 'ClassificationRules');
const BalanceSheet = page(() => import('./pages/BalanceSheet'), 'BalanceSheet');
const IncomeExpense = page(() => import('./pages/IncomeExpense'), 'IncomeExpense');
const Analytics = page(() => import('./pages/Analytics'), 'Analytics');
const MarketSentiment = page(() => import('./pages/MarketSentiment'), 'MarketSentiment');
const StrategyAlignment = page(() => import('./pages/StrategyAlignment'), 'StrategyAlignment');
const AIAdvisor = page(() => import('./pages/AIAdvisor'), 'AIAdvisor');
const Settings = page(() => import('./pages/Settings'), 'Settings');
const Valuation = page(() => import('./pages/Valuation'), 'Valuation');
const ValueTrapReviews = page(() => import('./pages/ValueTrapReviews'), 'ValueTrapReviews');
const CashFlowClassification = page(() => import('./pages/CashFlowClassification'), 'CashFlowClassification');
const MonthlyAttribution = page(() => import('./pages/MonthlyAttribution'), 'MonthlyAttribution');

function App() {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <CurrencyProvider>
    <LanguageProvider>
    <DemoModeProvider>
    <Router>
      <Layout>
        <Suspense fallback={<div style={{ padding: 32, color: 'var(--color-fg-4)' }}><span className="material-symbols-outlined" style={{ fontSize: 20, animation: 'spin 1s linear infinite' }}>sync</span></div>}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/risk" element={<RiskMatrix />} />
          <Route path="/performance" element={<Performance />} />
          <Route path="/wealth" element={<WealthOS />} />
          <Route path="/compass" element={<Compass />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/verify" element={<Verification />} />
          <Route path="/decisions" element={<DecisionHub />} />
          <Route path="/taxonomy" element={<Taxonomy />} />
          <Route path="/risk-profiles" element={<RiskProfiles />} />
          <Route path="/transactions" element={<TransactionBrowser />} />
          <Route path="/import" element={<ImportWorkbench />} />
          <Route path="/asset-class-audit" element={<AssetClassAudit />} />
          <Route path="/asset-audit" element={<AssetAudit />} />
          <Route path="/asset-case-file" element={<AssetCaseFile />} />
          <Route path="/tier-audit" element={<TierAudit />} />
          <Route path="/classification-rules" element={<ClassificationRules />} />
          <Route path="/balance-sheet" element={<BalanceSheet />} />
          <Route path="/income-expense" element={<IncomeExpense />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/market-sentiment" element={<MarketSentiment />} />
          <Route path="/strategy" element={<StrategyAlignment />} />
          <Route path="/ai-advisor" element={<AIAdvisor />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/ai-models" element={<Settings />} />
          <Route path="/ai-prompts" element={<Settings />} />
          <Route path="/data-sources" element={<Settings />} />
          <Route path="/valuation" element={<Valuation />} />
          <Route path="/value-trap-reviews" element={<ValueTrapReviews />} />
          <Route path="/cash-flow-classification" element={<CashFlowClassification />} />
          <Route path="/monthly-attribution" element={<MonthlyAttribution />} />
        </Routes>
        </Suspense>
      </Layout>
    </Router>
    </DemoModeProvider>
    </LanguageProvider>
    </CurrencyProvider>
  );
}

export default App;
