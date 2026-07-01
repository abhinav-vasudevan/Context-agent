import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import ForceGraph3D from 'react-force-graph-3d';
import * as THREE from 'three';
import { Target, Plus, Minus, Search, Info } from 'lucide-react';

// Cache materials globally so they are extremely fast and reuse memory
const materials = {
  core: new THREE.MeshLambertMaterial({ color: '#60a5fa' }), // Blue
  module: new THREE.MeshLambertMaterial({ color: '#4ade80' }), // Green
  data: new THREE.MeshLambertMaterial({ color: '#c084fc' }), // Purple
  default: new THREE.MeshLambertMaterial({ color: '#9ca3af' }),
  hover: new THREE.MeshLambertMaterial({ color: '#ffaa00' }),
  selected: new THREE.MeshLambertMaterial({ color: '#ffffff' }),
};

// Pre-create sphere geometries for each size to optimize performance
const geometries = {
  large: new THREE.SphereGeometry(10, 32, 32),
  medium: new THREE.SphereGeometry(7, 32, 32),
  small: new THREE.SphereGeometry(4, 32, 32),
  hover: new THREE.SphereGeometry(9, 32, 32),
  selected: new THREE.SphereGeometry(12, 32, 32),
};

export default function ArchitectureGraph({ astNodeCount = 0 }) {
  const [graphData, setGraphData] = useState({ nodes: [], links: [] });
  const [hoverNode, setHoverNode] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });
  const [activeTaxonomies, setActiveTaxonomies] = useState({
    core: true,
    modules: true,
    data: true,
    other: true
  });
  
  const containerRef = useRef(null);
  const fgRef = useRef(null);

  useEffect(() => {
    fetch('http://127.0.0.1:8088/api/graph')
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          setGraphData(data.graph);
        }
      })
      .catch(console.error);

    const observer = new ResizeObserver(entries => {
      if (entries[0]) {
        const { width, height } = entries[0].contentRect;
        setDimensions({ width, height });
      }
    });
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }
    return () => observer.disconnect();
  }, []);

  const filteredGraphData = useMemo(() => {
    if (!graphData.nodes.length) return { nodes: [], links: [] };
    
    const searchLower = searchQuery.toLowerCase();
    const nodes = graphData.nodes.filter(node => {
      if (searchQuery && !node.id.toLowerCase().includes(searchLower)) return false;
      
      const label = node.labels ? node.labels[0] : '';
      if (label === 'Subsystem' && !activeTaxonomies.core) return false;
      if (label === 'Module' && !activeTaxonomies.modules) return false;
      if (label === 'Service' && !activeTaxonomies.data) return false;
      if (!['Subsystem', 'Module', 'Service'].includes(label) && !activeTaxonomies.other) return false;
      
      return true;
    });
    
    const nodeIds = new Set(nodes.map(n => n.id));
    const links = graphData.links.filter(link => {
      const sourceId = typeof link.source === 'object' ? link.source.id : link.source;
      const targetId = typeof link.target === 'object' ? link.target.id : link.target;
      return nodeIds.has(sourceId) && nodeIds.has(targetId);
    });
    
    return { nodes, links };
  }, [graphData, activeTaxonomies, searchQuery]);

  // Tweak 3D physics engine for better spread
  useEffect(() => {
    if (fgRef.current && filteredGraphData.nodes.length > 0) {
      fgRef.current.d3Force('charge').strength(-150);
      fgRef.current.d3Force('link').distance(50);
    }
  }, [filteredGraphData]);

  const handleNodeClick = useCallback((node) => {
    setSelectedNode(node);
    if (fgRef.current) {
      const distance = 60;
      const distRatio = 1 + distance/Math.hypot(node.x, node.y, node.z);
      fgRef.current.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
        node,
        2000
      );
    }
  }, []);

  const handleRecenter = () => {
    if (fgRef.current) {
      fgRef.current.zoomToFit(1000);
    }
  };

  const handleZoom = (direction) => {
    if (fgRef.current) {
      const currentPos = fgRef.current.cameraPosition();
      const factor = direction === 'in' ? 0.6 : 1.4;
      fgRef.current.cameraPosition(
        { x: currentPos.x * factor, y: currentPos.y * factor, z: currentPos.z * factor },
        null,
        500
      );
    }
  };

  return (
    <div className="relative w-full h-full bg-[#101018] overflow-hidden font-sans rounded-lg">
      
      {/* Search Bar - Top Center/Left */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 w-96">
        <div className="relative">
          <Search className="absolute left-3 top-2.5 text-nude-500 w-4 h-4" />
          <input
            type="text"
            placeholder="Search knowledge graph..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full bg-[#12131c]/90 backdrop-blur border border-nude-800 rounded-full py-2 pl-9 pr-4 text-xs text-nude-200 outline-none focus:border-nude-600 shadow-xl placeholder-nude-600"
          />
        </div>
      </div>

      {/* 3D Force Graph Layer */}
      <div className="absolute inset-0 z-0" ref={containerRef}>
        <ForceGraph3D
          ref={fgRef}
          width={dimensions.width}
          height={dimensions.height}
          graphData={filteredGraphData}
          nodeLabel="id"
          nodeThreeObject={node => {
            let material = materials.default;
            let geometry = geometries.small;
            
            if (selectedNode && selectedNode.id === node.id) {
              material = materials.selected;
              geometry = geometries.selected;
            } else if (hoverNode && hoverNode.id === node.id) {
              material = materials.hover;
              geometry = geometries.hover;
            } else {
              const label = node.labels ? node.labels[0] : '';
              switch(label) {
                case 'Subsystem': material = materials.core; geometry = geometries.large; break;
                case 'Service': material = materials.data; geometry = geometries.medium; break;
                case 'Module': material = materials.module; geometry = geometries.small; break;
              }
            }
            
            return new THREE.Mesh(geometry, material);
          }}
          linkWidth={1.2}
          linkColor={() => 'rgba(255, 255, 255, 0.4)'}
          linkDirectionalParticles={2}
          linkDirectionalParticleWidth={1.5}
          linkDirectionalParticleColor={() => '#ffaa00'}
          linkDirectionalParticleSpeed={() => 0.005}
          onNodeHover={setHoverNode}
          onNodeClick={handleNodeClick}
          onBackgroundClick={() => setSelectedNode(null)}
          backgroundColor="rgba(0,0,0,0)"
        />
      </div>

      {/* Top-Left: Active Taxonomies & Network Metrics */}
      <div className="absolute top-4 left-4 z-10 w-56 flex flex-col gap-4 pointer-events-none">
        
        {/* Network Metrics */}
        <div className="bg-[#12131c]/90 backdrop-blur border border-nude-800/80 rounded-lg p-4 shadow-xl pointer-events-auto">
          <h3 className="text-[9px] font-bold text-nude-500 uppercase tracking-widest mb-3">Network Metrics</h3>
          <div className="flex gap-3">
            <div className="flex-1 bg-nude-900 border border-nude-800 rounded p-2 text-center">
              <div className="text-[10px] text-nude-400 mb-0.5">Nodes</div>
              <div className="text-sm font-bold text-white">{filteredGraphData.nodes.length}</div>
            </div>
            <div className="flex-1 bg-nude-900 border border-nude-800 rounded p-2 text-center">
              <div className="text-[10px] text-nude-400 mb-0.5">Edges</div>
              <div className="text-sm font-bold text-accent">{filteredGraphData.links.length}</div>
            </div>
          </div>
        </div>

        {/* AST Stats */}
        {astNodeCount > 0 && (
          <div className="bg-[#12131c]/90 backdrop-blur border border-nude-800/80 rounded-lg p-3 shadow-xl pointer-events-auto flex items-center justify-between">
            <div className="text-[10px] text-nude-400">AST Indexing</div>
            <div className="text-[10px] text-[#4ade80] font-mono">{astNodeCount} nodes</div>
          </div>
        )}

        {/* Taxonomies & Legend */}
        <div className="bg-[#12131c]/90 backdrop-blur border border-nude-800/80 rounded-lg p-4 shadow-xl pointer-events-auto">
          <h3 className="text-[9px] font-bold text-nude-500 uppercase tracking-widest mb-3">Active Taxonomies</h3>
          <div className="space-y-3 text-[11px] text-nude-300">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-[#60a5fa] shadow-[0_0_8px_#60a5fa]"></span> Core Entities</div>
              <input type="checkbox" checked={activeTaxonomies.core} onChange={e => setActiveTaxonomies(prev => ({...prev, core: e.target.checked}))} className="accent-accent cursor-pointer" />
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-[#4ade80] shadow-[0_0_8px_#4ade80]"></span> Modules</div>
              <input type="checkbox" checked={activeTaxonomies.modules} onChange={e => setActiveTaxonomies(prev => ({...prev, modules: e.target.checked}))} className="accent-accent cursor-pointer" />
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-[#c084fc] shadow-[0_0_8px_#c084fc]"></span> Data Sources</div>
              <input type="checkbox" checked={activeTaxonomies.data} onChange={e => setActiveTaxonomies(prev => ({...prev, data: e.target.checked}))} className="accent-accent cursor-pointer" />
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-full bg-[#9ca3af] shadow-[0_0_8px_#9ca3af]"></span> Other</div>
              <input type="checkbox" checked={activeTaxonomies.other} onChange={e => setActiveTaxonomies(prev => ({...prev, other: e.target.checked}))} className="accent-accent cursor-pointer" />
            </div>
          </div>
        </div>

      </div>

      {/* Top-Right: Node Inspector */}
      <div className="absolute top-4 right-4 z-10 w-72 bg-[#12131c]/90 backdrop-blur border border-nude-800/80 rounded-lg shadow-2xl flex flex-col max-h-[calc(100%-80px)]">
        <div className="p-3 border-b border-nude-800/50 flex items-center gap-2 text-xs font-bold text-nude-200 uppercase tracking-wider">
          <Info size={14} className="text-nude-500" /> Node Inspector
        </div>
        
        <div className="p-4 overflow-y-auto custom-scrollbar flex-1">
          {selectedNode ? (
            <div>
              <h2 className="text-sm font-bold text-white mb-4 break-all">{selectedNode.id}</h2>
              <div className="space-y-3 text-xs text-nude-400">
                <div className="flex justify-between border-b border-nude-800/50 pb-1.5">
                  <span>Type</span>
                  <span className="text-white">{selectedNode.labels?.[0] || 'Unknown'}</span>
                </div>
                <div className="flex justify-between border-b border-nude-800/50 pb-1.5">
                  <span>Degree</span>
                  <span className="text-white">
                    {filteredGraphData.links.filter(l => l.source.id === selectedNode.id || (l.target && l.target.id === selectedNode.id)).length}
                  </span>
                </div>
              </div>
              
              <h3 className="text-[9px] font-bold text-nude-500 uppercase tracking-widest mt-6 mb-2">Connections</h3>
              <div className="flex flex-col gap-1.5">
                {filteredGraphData.links
                  .filter(l => (l.source && l.source.id === selectedNode.id) || (l.target && l.target.id === selectedNode.id))
                  .map(l => {
                    const neighbor = l.source.id === selectedNode.id ? l.target : l.source;
                    return (
                      <div 
                        key={neighbor.id} 
                        className="text-[11px] p-2 bg-[#1e1e2d] border border-nude-800 rounded hover:border-[#ffaa00] hover:text-white cursor-pointer transition-colors"
                        onClick={() => handleNodeClick(neighbor)}
                      >
                        {neighbor.id}
                      </div>
                    );
                  })}
              </div>
            </div>
          ) : (
            <div className="h-32 flex flex-col items-center justify-center text-nude-500 gap-3">
              <svg className="w-6 h-6 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 15l-2 5L9 9l11 4-5 2zm0 0l5 5M7.188 2.239l.777 2.897M5.136 7.965l-2.898-.777M13.95 4.05l-2.122 2.122m-5.657 5.656l-2.12 2.122" />
              </svg>
              <span className="text-xs italic">Select a node to view details</span>
            </div>
          )}
        </div>
      </div>

      {/* Bottom-Right: Map Controls */}
      <div className="absolute bottom-4 right-4 z-10 flex flex-col gap-2">
        <button onClick={handleRecenter} title="Recenter Graph" className="w-8 h-8 bg-[#12131c]/90 backdrop-blur border border-nude-800 rounded flex items-center justify-center text-nude-400 hover:text-white hover:bg-nude-800 transition-colors shadow-lg">
          <Target size={16} />
        </button>
        <div className="bg-[#12131c]/90 backdrop-blur border border-nude-800 rounded flex flex-col shadow-lg overflow-hidden">
          <button onClick={() => handleZoom('in')} title="Zoom In" className="w-8 h-8 flex items-center justify-center text-nude-400 hover:text-white hover:bg-nude-800 transition-colors border-b border-nude-800">
            <Plus size={16} />
          </button>
          <button onClick={() => handleZoom('out')} title="Zoom Out" className="w-8 h-8 flex items-center justify-center text-nude-400 hover:text-white hover:bg-nude-800 transition-colors">
            <Minus size={16} />
          </button>
        </div>
      </div>

    </div>
  );
}
