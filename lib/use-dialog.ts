'use client';
import { useEffect, useRef } from 'react';
export function useDialog(open:boolean,onClose:()=>void){
 const close=useRef(onClose);useEffect(()=>{close.current=onClose},[onClose]);
 useEffect(()=>{if(!open)return;const previous=document.activeElement as HTMLElement|null;const dialog=document.querySelector<HTMLElement>('[role="dialog"]');const oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
 const focusable=()=>Array.from(dialog?.querySelectorAll<HTMLElement>('a[href],button:not([disabled]),input,select,[tabindex="0"]')||[]);
 focusable()[0]?.focus();
 const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();close.current()}if(e.key==='Tab'){const items=focusable();const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}};
 document.addEventListener('keydown',key);return()=>{document.removeEventListener('keydown',key);document.body.style.overflow=oldOverflow;previous?.focus()};
 },[open]);
}
