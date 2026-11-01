import { describe, expect, test } from 'vitest';
import { displayAssetName, assetBadge } from '../src/utils/assetDisplay';
import { localizedBilingualLabel } from '../src/utils/localizedClassName';
import { formatDate, formatTime } from '../src/utils/formatMoney';
import { niceStep } from '../pages/dashboard/DashboardCharts';

describe('displayAssetName', () => {
  test('a real name from the API wins', () => {
    expect(displayAssetName('CN_FUND_000001', '示例指数基金A')).toBe('示例指数基金A');
  });
  test('name that only echoes the id falls back to the ticker', () => {
    expect(displayAssetName('US_STK_BRK-B', 'US_STK_BRK-B')).toBe('BRK-B');
    expect(displayAssetName('US_ETF_VOO')).toBe('VOO');
  });
  test('RSU ids keep the RSU marker', () => {
    expect(displayAssetName('RSU_TEST')).toBe('TEST RSU');
  });
  test('other prefixes drop the prefix and underscores', () => {
    expect(displayAssetName('ALTS_Test_Gold')).toBe('Test Gold');
  });
  test('unknown ids are returned as-is', () => {
    expect(displayAssetName('UNKNOWN')).toBe('UNKNOWN');
  });
});

describe('assetBadge', () => {
  test('maps prefixes to short market codes', () => {
    expect(assetBadge('US_STK_BRK-B')).toBe('US');
    expect(assetBadge('CN_FUND_000001')).toBe('CN');
    expect(assetBadge('RSU_TEST')).toBe('RSU');
    expect(assetBadge('ALTS_Test_Gold')).toBe('ALT');
  });
});

describe('localizedBilingualLabel', () => {
  test('English UI shows the English half', () => {
    expect(localizedBilingualLabel('Equity (股票)', 'en')).toBe('Equity');
    expect(localizedBilingualLabel('CN Equity (A股)', 'en')).toBe('CN Equity');
  });
  test('Chinese UI shows the Chinese half', () => {
    expect(localizedBilingualLabel('Equity (股票)', 'zh-CN')).toBe('股票');
    expect(localizedBilingualLabel('Fixed Income (固定收益)', 'zh-CN')).toBe('固定收益');
  });
  test('labels without a Chinese half are unchanged in both languages', () => {
    expect(localizedBilingualLabel('HK ETF', 'en')).toBe('HK ETF');
    expect(localizedBilingualLabel('HK ETF', 'zh-CN')).toBe('HK ETF');
    expect(localizedBilingualLabel('Bonds (USD)', 'zh-CN')).toBe('Bonds (USD)');
  });
  test('empty input gives an empty string', () => {
    expect(localizedBilingualLabel(null, 'en')).toBe('');
  });
});

describe('date-only strings keep their calendar date', () => {
  test('a date-only string is local midnight, not UTC midnight', () => {
    expect(formatDate('2026-10-12', 'en', { year: 'numeric', month: '2-digit', day: '2-digit' }))
      .toBe('10/12/2026');
    expect(formatTime('2026-10-12', 'en', { hour: '2-digit', minute: '2-digit', hour12: false }))
      .toBe('00:00');
  });
});

describe('niceStep', () => {
  test('rounds to 1/2/2.5/5 × 10^n', () => {
    expect(niceStep(3_500_000)).toBe(1_000_000);
    expect(niceStep(800_000)).toBe(200_000);
    expect(niceStep(9_000)).toBe(2_500);
  });
  test('non-positive span falls back to 1', () => {
    expect(niceStep(0)).toBe(1);
  });
});

describe('Chinese compact money below 1万', () => {
  test('is a whole number with grouping, not two bare decimals', async () => {
    const { formatMoneyStr } = await import('../src/utils/formatMoney');
    expect(formatMoneyStr(9013.37, 'zh-CN', { compact: true, symbol: '¥' })).toBe('¥9,013');
    expect(formatMoneyStr(12_345, 'zh-CN', { compact: true, symbol: '¥' })).toBe('¥1.23万');
  });
});

describe('assetTitle', () => {
  test('US listings read as their ticker', async () => {
    const { assetTitle } = await import('../src/utils/assetDisplay');
    expect(assetTitle('US_STK_QQQ', 'INVSC QQQ TRUST SRS 1 ETF')).toBe('QQQ');
  });
  test('other assets use the real name', async () => {
    const { assetTitle } = await import('../src/utils/assetDisplay');
    expect(assetTitle('CN_FUND_000001', '示例混合A')).toBe('示例混合A');
    expect(assetTitle('CN_FUND_000001', 'CN_FUND_000001')).toBe('000001');
  });
});
