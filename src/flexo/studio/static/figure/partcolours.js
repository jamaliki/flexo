// The colours of a figure's parts chosen (parts.js), for Set Colour… (⇧⌘C, the studio's
// colourkey.js): the colours of their own that win over their tone and the theme -- a shape's
// Fill, Outline and Text, a group's Background, Border and Title (by the shape's names, where
// both are chosen) -- each one edit of the figure, named as the inspector's Custom colours
// name it ("Change Colour"). A line takes the theme's tones alone: none of its own. A structure
// and a plot are drawn in colours of their own.

import { boxAround } from "/static/studio/hexcolour.js";

const PAINTS = [["fill", "Fill", "Background"], ["stroke", "Outline", "Border"], ["label", "Text", "Title"]];
const OWN_COLOURS = new Set(["structure", "plot"]);

// The parts chosen as a kind of colourKey's (`word`: what one is called -- "Shape", a slide's
// "Figure Shape"): null with none of them taking a colour of its own.
export function partColours(parts, { word = "Shape" } = {}) {
  if (!parts?.model || parts.inline) return null;
  const root = parts.model.root;
  const ids = (parts.selected || []).filter((id) => id && id !== root);
  const nodes = ids.map((id) => parts.nodeOf(id)).filter((node) => node && !OWN_COLOURS.has(node.kind));
  const groups = ids.map((id) => parts.groupOf(id)).filter((group) => group && !group.implied && group.id !== root);
  const count = nodes.length + groups.length;
  if (!count) return null;
  const common = (values) => (values.every((value) => value === values[0]) ? values[0] : undefined);
  const colours = PAINTS.map(([part, name, groupName]) => ({
    name: nodes.length ? name : groupName,
    value: common([...nodes.map((node) => node.properties?.[`paint-${part}`] ?? null), ...groups.map((group) => group.paint?.[part] ?? null)]),
    set: (hex) => {
      if (nodes.length) parts.act({ do: "update", targets: nodes.map((node) => ({ type: "node", id: node.id })), values: { [`properties.paint-${part}`]: hex } }, { select: false });
      if (groups.length) parts.act({ do: "update", targets: groups.map((group) => ({ type: "group", id: group.id })), values: { [`paint.${part}`]: hex } }, { select: false });
    },
  }));
  const one = count === 1 ? (nodes[0] || groups[0]).id : null;
  // A text shape is seen by its words.
  const main = nodes.length && nodes.every((node) => node.kind === "text") ? 2 : 0;
  return { noun: one ? `“${parts.nameOf(one)}”` : `${count} ${word}s`, colours, main };
}

// Where the parts chosen are drawn, on the screen: `element(id)` their drawing.
export function partsBox(parts, element) {
  const root = parts?.model?.root;
  return boxAround((parts?.selected || []).filter((id) => id !== root).map((id) => element(id)));
}
