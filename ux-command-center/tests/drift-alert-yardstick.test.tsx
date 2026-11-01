import React from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import { act, render, screen } from '../test-utils';
import { ActionCenter } from '../pages/dashboard/DashboardCards';
import type { DecisionAlert } from '../src/services/api';
import i18n from '../src/i18n';

// Round 7 #1: every drift alert names the targets it measured against, and
// says "(default)" while the active risk profile is the seeded one the user
// never chose. The Decision Hub renders the same component (DriftAlertText).

function driftAlert(yardstick: Record<string, unknown>): DecisionAlert {
  return {
    category: 'drift',
    priority: 'high',
    title: 'Equity allocation drifted 28.4% from target · vs risk profile: Balanced (default)',
    message: 'Current: 83.4% | Target: 55.0%',
    data: {
      asset_class: 'Equity',
      asset_class_cn: '股票',
      drift_pct: 28.4,
      actual_pct: 83.4,
      target_pct: 55.0,
      basis: yardstick.kind,
      yardstick,
    },
  };
}

const DEFAULT_PROFILE = { kind: 'risk_profile', profile_id: 2, profile_name: 'Balanced', is_default: true };

describe('drift alert yardstick', () => {
  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('names the default risk profile and links to Risk Profiles (EN)', () => {
    render(<ActionCenter alerts={[driftAlert(DEFAULT_PROFILE)]} />);

    expect(screen.getByText('Equity allocation drifted 28.4% from target')).toBeInTheDocument();
    const line = screen.getByTestId('drift-yardstick');
    expect(line).toHaveTextContent('vs risk profile: Balanced (default) — change');
    expect(screen.getByRole('link', { name: 'change' })).toHaveAttribute('href', '/risk-profiles');
  });

  it('renders the same line in Chinese', async () => {
    await act(async () => {
      await i18n.changeLanguage('zh-CN');
    });
    render(<ActionCenter alerts={[driftAlert(DEFAULT_PROFILE)]} />);

    expect(screen.getByText('股票配置偏离目标 28.4%')).toBeInTheDocument();
    expect(screen.getByText('当前：83.4% | 目标：55.0%')).toBeInTheDocument();
    expect(screen.getByTestId('drift-yardstick')).toHaveTextContent('对照风险档位：Balanced（默认）— 修改');
    expect(screen.getByRole('link', { name: '修改' })).toHaveAttribute('href', '/risk-profiles');
  });

  it('drops the default marker once the user has chosen the profile', () => {
    render(<ActionCenter alerts={[driftAlert({ ...DEFAULT_PROFILE, is_default: false })]} />);

    const line = screen.getByTestId('drift-yardstick');
    expect(line).toHaveTextContent('vs risk profile: Balanced — change');
    expect(line).not.toHaveTextContent('(default)');
  });

  it('names strategic targets without a profile link', () => {
    render(<ActionCenter alerts={[driftAlert({ kind: 'strategic' })]} />);

    expect(screen.getByTestId('drift-yardstick')).toHaveTextContent('vs strategic targets');
    expect(screen.queryByRole('link', { name: 'change' })).toBeNull();
  });

  it('leaves non-drift alerts as the backend wrote them', () => {
    const alert: DecisionAlert = {
      category: 'verification', priority: 'medium', title: 'Verify AAPL call', message: 'Due in 3 days', data: {},
    };
    render(<ActionCenter alerts={[alert]} />);

    expect(screen.getByText('Verify AAPL call')).toBeInTheDocument();
    expect(screen.queryByTestId('drift-yardstick')).toBeNull();
  });
});
