import { test } from 'node:test';
import assert from 'node:assert/strict';
import { insertMarkdown } from '../../tmp/frontend-unit-tests/features/documents/markdown-edit.js';
test('한글 선택을 강조하고 내부 선택을 보존한다',()=>{assert.deepEqual(insertMarkdown('안녕 세계',0,2,'bold'),{text:'**안녕** 세계',start:2,end:4,overflow:false})});
test('빈 선택에 예시를 넣고 선택한다',()=>{const r=insertMarkdown('',0,0,'italic');assert.equal(r.text,'*강조할 내용*');assert.equal(r.text.slice(r.start,r.end),'강조할 내용')});
test('선택된 줄에 번호를 붙이며 다음 줄 시작은 포함하지 않는다',()=>{assert.equal(insertMarkdown('하나\n둘\n셋',0,5,'number').text,'1. 하나\n2. 둘\n셋')});
test('제목 글머리 인용을 줄마다 추가한다',()=>{for(const [a,p] of [['heading','## '],['bullet','- '],['quote','> ']])assert.equal(insertMarkdown('가\n나',0,3,a).text,p+'가\n'+p+'나')});
test('링크의 URL을 선택한다',()=>{const r=insertMarkdown('휴가',0,2,'link');assert.equal(r.text,'[휴가](https://example.com)');assert.equal(r.text.slice(r.start,r.end),'https://example.com')});
test('코드의 백틱보다 긴 구분자를 사용한다',()=>{const r=insertMarkdown('```\n코드',0,6,'code');assert.equal(r.text,'````\n```\n코드\n````');assert.equal(r.text.slice(r.start,r.end),'```\n코드')});
test('중간 코드 삽입은 독립 줄로 만든다',()=>{assert.equal(insertMarkdown('앞뒤',1,1,'code').text,'앞\n```\n코드를 입력하세요\n```\n뒤')});
test('50000자 초과는 원문과 선택을 유지한다',()=>{const text='가'.repeat(50000);assert.deepEqual(insertMarkdown(text,1,2,'bold'),{text,start:1,end:2,overflow:true})});

test('첫 빈 줄 시작의 제목 삽입 위치',()=>{assert.equal(insertMarkdown('\n다음',0,0,'heading').text,'## \n다음')});
