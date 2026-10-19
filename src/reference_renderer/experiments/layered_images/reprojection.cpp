#include "experiment.hpp"

namespace layered_images {
thread_local std::ofstream* native_stream=nullptr;
thread_local std::map<std::uint32_t,std::uint16_t> native_palette;
namespace {
void record_fragment(int x,int y,double depth,std::uint32_t rgb) {
    if(!native_stream) return;
    const auto offset=static_cast<std::uint16_t>(((y/8)*11+x/8)*64+(y%8)*8+x%8);
    const auto z=static_cast<std::uint16_t>(std::clamp(std::round(depth*8),0.0,65534.0));
    const std::array<std::uint16_t,3> record{offset,z,native_palette.at(rgb)};
    native_stream->write(reinterpret_cast<const char*>(record.data()),6);
}
struct Vertex { double x,y,z; };
double quantize(double z,int bits) {
    if(bits==32 || z<=0) return z;
    const double levels=static_cast<double>((1U<<bits)-1U);
    return std::exp2(std::round(std::clamp((std::log2(z)+2)/15,0.0,1.0)*levels)/levels*15-2);
}
double edge(Vertex a,Vertex b,double x,double y) {return (b.x-a.x)*(y-a.y)-(b.y-a.y)*(x-a.x);}
void triangle(Image& image,Vertex a,Vertex b,Vertex c,std::uint32_t rgb) {
    double area=edge(a,b,c.x,c.y);
    if(std::abs(area)<1e-9) return;
    if(area<0) {std::swap(b,c);area=-area;}
    const int minx=std::max(0,static_cast<int>(std::floor(std::min({a.x,b.x,c.x}))));
    const int maxx=std::min(width-1,static_cast<int>(std::ceil(std::max({a.x,b.x,c.x}))));
    const int miny=std::max(0,static_cast<int>(std::floor(std::min({a.y,b.y,c.y}))));
    const int maxy=std::min(height-1,static_cast<int>(std::ceil(std::max({a.y,b.y,c.y}))));
    for(int y=miny;y<=maxy;++y) for(int x=minx;x<=maxx;++x) {
        const double wa=edge(b,c,x+.5,y+.5),wb=edge(c,a,x+.5,y+.5),wc=edge(a,b,x+.5,y+.5);
        if(std::min({wa,wb,wc})<-1e-8) continue;
        const double inv=(wa/a.z+wb/b.z+wc/c.z)/area;
        if(inv<=0) continue;
        const auto p=static_cast<std::size_t>(y*width+x);
        const auto z=static_cast<float>(1/inv);
        record_fragment(x,y,z,rgb);
        ++image.fragments;
        if(z<image.depth[p]) {image.depth[p]=z;image.rgb[p]=rgb;}
    }
}
}

Image reproject(const Capture& capture,const ViewTransform& target,const Json& variant) {
    const int layers=variant.at("layers"),padding=variant.at("padding"),density=variant.at("density");
    const int bits=variant.value("depthBits",32),radius=variant.value("hiddenEdgeRadius",-1);
    const std::string footprint=variant.at("footprint");
    const double scale=variant.value("splatScale",1.0);
    if(layers<1 || layers>capture.layers || padding<0 || padding>capture.padding || density<1 || capture.density%density
       || (bits!=8 && bits!=12 && bits!=16 && bits!=32) || radius < -1 || scale<.5 || scale>2
       || (footprint!="point" && footprint!="flat" && footprint!="gradient" && footprint!="plane-oracle"))
        fail("variant escapes capture or supported representation");
    const int stride=capture.density/density;
    const int offset=(capture.padding-padding)*capture.density+(stride-1)/2;
    const int w=(width+padding*2)*density,h=(height+padding*2)*density;
    std::vector<std::uint8_t> edges(static_cast<std::size_t>(w*h),radius<0 ? 1:0);
    const auto get=[&](int layer,int x,int y)->const Sample& {return capture.at(layer,offset+x*stride,offset+y*stride);};
    if(radius>=0) {
        for(int y=0;y<h;++y) for(int x=0;x<w;++x) {
            const auto z=get(0,x,y).depth;
            bool discontinuity=z<=0;
            for(const auto d:std::array<std::array<int,2>,4>{{{1,0},{-1,0},{0,1},{0,-1}}}) {
                const int xx=x+d[0],yy=y+d[1];
                if(xx<0 || yy<0 || xx>=w || yy>=h) {discontinuity=true;continue;}
                const auto other=get(0,xx,yy).depth;
                discontinuity=discontinuity || other<=0 || std::abs(other-z)>.15*std::min(other,z);
            }
            if(discontinuity) for(int yy=std::max(0,y-radius*density);yy<=std::min(h-1,y+radius*density);++yy)
                for(int xx=std::max(0,x-radius*density);xx<=std::min(w-1,x+radius*density);++xx)
                    edges[static_cast<std::size_t>(yy*w+xx)]=1;
        }
    }
    Image out;
    out.rgb.resize(width*height);out.depth.resize(width*height);
    std::size_t hidden=0;
    for(int layer=0;layer<layers;++layer) for(int y=0;y<h;++y) for(int x=0;x<w;++x) {
        if(layer>0 && !edges[static_cast<std::size_t>(y*w+x)]) continue;
        const auto& sample=get(layer,x,y);
        if(sample.depth<=0) continue;
        ++out.samples; hidden+=layer>0;
        const double z=quantize(sample.depth,bits);
        const double u=(x+.5)/density-padding,v=(y+.5)/density-padding;
        const auto direction=capture.view.forward+capture.view.screen_right*((u-42)/64)+capture.view.up*((37-v)/64);
        const auto point=capture.view.origin+direction*z;
        const auto project=[&](Vec3 p) {
            const auto delta=p-target.origin;
            const double d=dot(delta,target.forward);
            return Vertex{42+64*dot(delta,target.screen_right)/d,37-64*dot(delta,target.up)/d,d};
        };
        const auto center=project(point);
        if(center.z<=.01 || !std::isfinite(center.x) || !std::isfinite(center.y)) continue;
        if(footprint=="point") {
            if(center.x<0 || center.y<0 || center.x>=width || center.y>=height) continue;
            const auto p=static_cast<std::size_t>(static_cast<int>(center.y)*width+static_cast<int>(center.x));
            ++out.fragments;
            record_fragment(static_cast<int>(center.x),static_cast<int>(center.y),center.z,sample.rgb);
            if(center.z<out.depth[p]) {out.depth[p]=static_cast<float>(center.z);out.rgb[p]=sample.rgb;}
            continue;
        }
        double gx=0,gy=0;
        if(footprint=="gradient") {
            const auto gradient=[&](int dx,int dy) {
                double best=0,best_jump=std::numeric_limits<double>::infinity();
                for(int sign: {-1,1}) {
                    const int xx=x+sign*dx,yy=y+sign*dy;
                    if(xx<0 || yy<0 || xx>=w || yy>=h) continue;
                    const double other=quantize(get(layer,xx,yy).depth,bits);
                    const double jump=std::abs(other-z);
                    if(other>0 && jump<.2*std::min(other,z) && jump<best_jump) {
                        best=(1/other-1/z)*sign*density;best_jump=jump;
                    }
                }
                return best;
            };
            gx=gradient(1,0);gy=gradient(0,1);
        } else if(footprint=="plane-oracle") {
            const Vec3 n{sample.normal[0],sample.normal[1],sample.normal[2]};
            const double distance=dot(n,direction)*z;
            if(std::abs(distance)>1e-9) {gx=dot(n,capture.view.screen_right)/(64*distance);gy=-dot(n,capture.view.up)/(64*distance);}
        }
        std::array<Vertex,4> corners{};
        bool valid=true;
        for(std::size_t i=0;i<4;++i) {
            const double du=(i==0 || i==3 ? -.5:.5)*scale/density;
            const double dv=(i<2 ? -.5:.5)*scale/density;
            const double inv=1/z+gx*du+gy*dv;
            if(inv<=0) {valid=false;break;}
            const auto ray=direction+capture.view.screen_right*(du/64)-capture.view.up*(dv/64);
            corners[i]=project(capture.view.origin+ray*(1/inv));
            valid=valid && corners[i].z>.01 && std::abs(corners[i].x)<100000 && std::abs(corners[i].y)<100000;
        }
        // Conservative near-plane rejection is included in gap/error metrics.
        if(!valid) continue;
        triangle(out,corners[0],corners[1],corners[2],sample.rgb);
        triangle(out,corners[0],corners[2],corners[3],sample.rgb);
    }
    // Dense front image + occupancy; deeper samples may use packed 16-bit locations.
    const std::size_t front=static_cast<std::size_t>(w*h);
    const std::size_t data_bits=(front+(radius<0 ? front*static_cast<std::size_t>(layers-1):hidden))*static_cast<std::size_t>(8+bits);
    out.bytes=(data_bits+7)/8+(front*static_cast<std::size_t>(layers)+7)/8+(radius<0 ? 0:hidden*2);
    if(footprint=="plane-oracle") out.bytes+=out.samples*12;
    const auto logical_rgb=out.rgb;
    std::vector<std::uint32_t> mask(width*height);
    for(std::size_t i=0;i<mask.size();++i) mask[i]=std::isfinite(out.depth[i]) ? 1:0;
    const auto full_mask=present_x3(mask,{});
    out.rgb=present_x3(logical_rgb,{});
    out.depth.resize(display_pixels);
    for(std::size_t i=0;i<out.depth.size();++i) out.depth[i]=full_mask[i] ? 1.0F:std::numeric_limits<float>::infinity();
    return out;
}
} // namespace layered_images
