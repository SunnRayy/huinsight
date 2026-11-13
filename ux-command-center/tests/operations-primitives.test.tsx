import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { CardHeader, ChipBtn, FieldLabel, FormTextarea, InfoTip, ModalShell, Notice } from '../components/operations';

describe('CardHeader', () => {
  it('renders the title, mono subline and right slot', () => {
    render(<CardHeader icon="query_stats" title="Returns inputs" sub="used by Returns" right={<span>pill</span>} />);
    expect(screen.getByRole('heading', { name: 'Returns inputs' })).toBeInTheDocument();
    expect(screen.getByText('used by Returns')).toHaveStyle({ fontFamily: 'var(--font-mono)' });
    expect(screen.getByText('pill')).toBeInTheDocument();
    expect(screen.getByText('query_stats')).toBeInTheDocument();
  });
});

describe('InfoTip', () => {
  it('opens on hover, focus and tap, links the tooltip, and closes on Esc', () => {
    render(<InfoTip label="Why">Because the month has no trades.</InfoTip>);
    const button = screen.getByRole('button', { name: 'Why' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.mouseEnter(button.parentElement!);
    const tip = screen.getByRole('tooltip');
    expect(tip).toHaveTextContent('Because the month has no trades.');
    expect(button).toHaveAttribute('aria-describedby', tip.id);
    fireEvent.mouseLeave(button.parentElement!);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.focus(button);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    fireEvent.keyDown(button, { key: 'Escape' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    fireEvent.blur(button);
    fireEvent.click(button); // tap
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
  });
});

describe('Notice', () => {
  it('announces success politely', () => {
    render(<Notice>Done.</Notice>);
    expect(screen.getByRole('status')).toHaveTextContent('Done.');
    expect(screen.getByText('check_circle')).toBeInTheDocument();
  });

  it('announces danger as an alert, with the server reason verbatim and an action', () => {
    const onClick = vi.fn();
    render(<Notice tone="danger" detail="covered_to must be before today" action={<ChipBtn onClick={onClick}>Edit</ChipBtn>}>Couldn't save.</Notice>);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent("Couldn't save.");
    expect(screen.getByText('covered_to must be before today')).toHaveStyle({ fontFamily: 'var(--font-mono)' });
    fireEvent.click(screen.getByText('Edit'));
    expect(onClick).toHaveBeenCalled();
  });

  it.each([['warning', 'warning'], ['info', 'info']] as const)('uses the %s icon', (tone, icon) => {
    render(<Notice tone={tone}>x</Notice>);
    expect(screen.getByText(icon)).toBeInTheDocument();
  });
});

describe('FormTextarea', () => {
  it('passes the value string to onChange and pairs with FieldLabel', () => {
    const onChange = vi.fn();
    render(<><FieldLabel htmlFor="n">Note</FieldLabel><FormTextarea id="n" value="" onChange={onChange} rows={4} /></>);
    const area = screen.getByLabelText('Note');
    expect(area.tagName).toBe('TEXTAREA');
    expect(area).toHaveAttribute('rows', '4');
    fireEvent.change(area, { target: { value: 'checked the app' } });
    expect(onChange).toHaveBeenCalledWith('checked the app');
  });
});

describe('ModalShell', () => {
  it('is a labelled dialog with a named close button', () => {
    const onClose = vi.fn();
    render(<ModalShell title="Declare" onClose={onClose} closeLabel="Cancel">body</ModalShell>);
    expect(screen.getByRole('dialog', { name: 'Declare' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onClose).toHaveBeenCalled();
  });
});
